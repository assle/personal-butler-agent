"""
Phase 1 研究执行器测试
验证 Worker 生成明确标记为未审核的单次 LLM 初稿，并保持幂等。
"""
from unittest.mock import AsyncMock

import pytest

from src.research.executor import FoundationResearchExecutor
from src.research.service import ResearchTaskService


@pytest.mark.asyncio
async def test_executor_persists_unreviewed_foundation_report(db_session):
    """执行器生成初稿并完成任务"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="比较 Taskiq 与 Celery",
    )
    llm = AsyncMock()
    llm.chat.return_value = "## 初步结论\nTaskiq 更贴近异步项目。"
    executor = FoundationResearchExecutor(service, llm)

    report = await executor.execute(db_session, task.id)

    assert report.quality_status == "unreviewed_foundation"
    assert report.body.startswith("## 初步结论")
    llm.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_executor_is_idempotent_after_report_exists(db_session):
    """重复投递同一任务不会重复调用 LLM 或创建第二份报告"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="研究问题",
    )
    llm = AsyncMock()
    llm.chat.return_value = "初稿"
    executor = FoundationResearchExecutor(service, llm)
    first = await executor.execute(db_session, task.id)
    second = await executor.execute(db_session, task.id)
    assert second.id == first.id
    assert llm.chat.await_count == 1
