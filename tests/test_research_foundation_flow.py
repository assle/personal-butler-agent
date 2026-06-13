"""
异步研究 Phase 1 端到端测试
使用真实服务和 ORM、假队列/LLM/企微客户端验证完整基础链路。
"""
import re
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.agents.private_butler import PrivateButlerAgent
from src.messaging import InboundMessage, dispatch_message
from src.models.research import ResearchDelivery, ResearchReport, ResearchTask
from src.models.workspace import Workspace
from src.research.delivery import ResearchDeliveryService
from src.research.executor import FoundationResearchExecutor
from src.research.service import ResearchTaskService
from src.research.submission import ResearchSubmissionService


class RecordingDispatcher:
    """记录研究和投递任务 ID 的内存 dispatcher"""

    def __init__(self):
        """初始化记录列表"""
        self.planning_ids: list[str] = []
        self.delivery_ids: list[str] = []
        self.research_ids: list[str] = []

    async def enqueue_planning(self, task_id: str) -> None:
        """记录规划任务 ID"""
        self.planning_ids.append(task_id)

    async def enqueue_delivery(self, task_id: str) -> None:
        """记录投递任务 ID"""
        self.delivery_ids.append(task_id)

    async def enqueue_research(self, task_id: str) -> None:
        """记录研究任务 ID（legacy）"""
        self.research_ids.append(task_id)


@pytest.mark.asyncio
async def test_private_research_foundation_flow_is_durable_and_idempotent(
    db_session,
):
    """私聊提交、生成初稿、主动投递和重复回调形成完整闭环"""
    # 确保 backward-compat 路径的默认工作空间存在
    db_session.add(
        Workspace(id="default", name="Default Workspace", status="active")
    )
    await db_session.flush()

    tasks = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    dispatcher = RecordingDispatcher()
    submitter = ResearchSubmissionService(tasks, dispatcher)
    private_agent = PrivateButlerAgent(
        llm_client=AsyncMock(),
        summary_agent=AsyncMock(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
        research_submitter=submitter,
    )
    inbound = InboundMessage(
        source="wecom_callback",
        msg_id="msg-flow-1",
        msg_type="text",
        user_id="open-u1",
        content="深度研究：比较 Taskiq 和 Celery",
        chat_type="single",
        chat_id=None,
        response_url="https://example.test/reply",
        raw={},
    )

    first = await dispatch_message(
        inbound,
        db_session,
        private_agent=private_agent,
        group_agent=AsyncMock(),
    )
    duplicate = await dispatch_message(
        inbound,
        db_session,
        private_agent=private_agent,
        group_agent=AsyncMock(),
    )

    task_id = re.search(r"R\d{8}-[A-F0-9]{8}", first.reply).group(0)
    rows = (await db_session.execute(select(ResearchTask))).scalars().all()
    assert duplicate.reply == first.reply
    assert len(rows) == 1
    assert dispatcher.planning_ids == [task_id]

    llm = AsyncMock()
    llm.chat.return_value = "## 初步结论\nTaskiq 更贴近 async 项目。"
    report = await FoundationResearchExecutor(tasks, llm).execute(
        db_session, task_id
    )
    assert report.quality_status == "unreviewed_foundation"
    # 标记报告为已验证，使投递通过质量门
    report.report_status = "validated"
    await db_session.flush()

    app_client = AsyncMock()
    app_client.convert_open_userid.return_value = "plain-u1"
    app_client.send_text.return_value = "wecom-msg-1"
    delivery = await ResearchDeliveryService(tasks, app_client).deliver(
        db_session, task_id
    )
    assert delivery.status == "delivered"
    sent_content = app_client.send_text.await_args.args[1]
    assert "尚未进行多来源检索、逐项引用和独立审核" in sent_content

    stored_report = (
        await db_session.execute(
            select(ResearchReport).where(ResearchReport.task_id == task_id)
        )
    ).scalar_one()
    stored_delivery = await db_session.get(ResearchDelivery, task_id)
    assert stored_report.body.startswith("## 初步结论")
    assert stored_delivery.wecom_msgid == "wecom-msg-1"


@pytest.mark.asyncio
async def test_group_message_does_not_use_private_research_submitter(db_session):
    """群聊研究文本仍走群场景，不进入私聊研究队列"""
    dispatcher = RecordingDispatcher()
    tasks = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    private_agent = AsyncMock()
    group_agent = AsyncMock()
    group_agent.handle.return_value.reply = "群聊不开放研究任务。"
    group_agent.handle.return_value.data = {"intent": "group_mention"}

    await dispatch_message(
        InboundMessage(
            source="wecom_callback",
            msg_id="msg-group-research",
            msg_type="text",
            user_id="open-u1",
            content="深度研究：比较 Taskiq 和 Celery",
            chat_type="group",
            chat_id="group-1",
            response_url="https://example.test/reply",
            raw={},
        ),
        db_session,
        private_agent=private_agent,
        group_agent=group_agent,
    )

    private_agent.handle.assert_not_awaited()
    assert dispatcher.research_ids == []
