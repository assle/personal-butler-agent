"""
Taskiq 核心任务函数测试
不连接 Redis，验证研究、超时、失败和独立投递重试。
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models.research import ResearchTask
from src.models.research_execution import ResearchPlan, ResearchStep
from src.models.workspace import Workspace
from src.research.tasks import (
    execute_delivery_job,
    execute_research_job,
    execute_step_job,
)


class _SessionContext:
    """复用 pytest AsyncSession 的测试上下文"""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        """返回测试会话"""
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        """不关闭 fixture 管理的会话"""
        return False


def _session_factory(session):
    """构造兼容 worker 的会话工厂"""
    return lambda: _SessionContext(session)


async def _seed_running_step(db_session, *, task_id: str, owner: str) -> ResearchStep:
    """创建已被调度器认领的运行中步骤

    参数:
        db_session: 测试数据库会话
        task_id: 研究任务 ID
        owner: 调度器持久化的租约所有者

    返回:
        ResearchStep: 已写入数据库的运行中步骤
    """
    workspace = Workspace(id=f"ws-{task_id}", name=f"workspace-{task_id}")
    db_session.add(workspace)
    await db_session.flush()
    task = ResearchTask(
        id=task_id,
        source_msgid=f"msg-{task_id}",
        requester_open_userid="u1",
        workspace_id=workspace.id,
        question="test",
        research_type="foundation",
        status="running",
        access_scope={},
        max_rounds=4,
        timeout_seconds=300,
        current_round=0,
        cancel_requested=False,
    )
    db_session.add(task)
    await db_session.flush()
    plan = ResearchPlan(
        workspace_id=workspace.id,
        task_id=task_id,
        version=1,
        objective="test",
        completion_criteria=["done"],
        estimated_cost_microunits=100,
        estimated_tokens=100,
        raw_plan={},
    )
    db_session.add(plan)
    await db_session.flush()
    step = ResearchStep(
        id=f"{task_id}:1:search",
        workspace_id=workspace.id,
        task_id=task_id,
        plan_id=plan.id,
        kind="web_retrieval",
        tool_name="web.search",
        input_payload={"query": "test"},
        status="running",
        idempotency_key=f"{task_id}:search",
        owner=owner,
        attempt_count=1,
    )
    db_session.add(step)
    await db_session.flush()
    return step


@pytest.mark.asyncio
async def test_execute_research_job_commits_report_then_enqueues_delivery(db_session):
    """研究任务提交报告后单独派发 delivery"""
    executor = AsyncMock()
    dispatcher = AsyncMock()
    task_service = AsyncMock()

    await execute_research_job(
        "R20260612-ABCDEF12",
        session_factory=_session_factory(db_session),
        executor=executor,
        dispatcher=dispatcher,
        task_service=task_service,
        timeout_seconds=300,
    )

    executor.execute.assert_awaited_once_with(
        db_session, "R20260612-ABCDEF12"
    )
    dispatcher.enqueue_delivery.assert_awaited_once_with(
        "R20260612-ABCDEF12"
    )
    task_service.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_research_job_marks_failure_and_does_not_enqueue_delivery(
    db_session,
):
    """研究执行失败时记录失败且不投递"""
    executor = AsyncMock()
    executor.execute.side_effect = RuntimeError("llm down")
    dispatcher = AsyncMock()
    task_service = AsyncMock()

    with pytest.raises(RuntimeError, match="llm down"):
        await execute_research_job(
            "R20260612-ABCDEF12",
            session_factory=_session_factory(db_session),
            executor=executor,
            dispatcher=dispatcher,
            task_service=task_service,
            timeout_seconds=300,
        )

    task_service.mark_failed.assert_awaited_once()
    dispatcher.enqueue_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_research_job_marks_timeout(db_session):
    """超过硬预算时通过 mark_timed_out 记录为 failed 状态"""
    async def never_finishes(db, task_id):
        """模拟超时任务"""
        await asyncio.sleep(1)

    executor = AsyncMock()
    executor.execute.side_effect = never_finishes
    dispatcher = AsyncMock()
    task_service = AsyncMock()

    with pytest.raises(TimeoutError):
        await execute_research_job(
            "R20260612-ABCDEF12",
            session_factory=_session_factory(db_session),
            executor=executor,
            dispatcher=dispatcher,
            task_service=task_service,
            timeout_seconds=0.001,
        )

    task_service.mark_timed_out.assert_awaited_once()
    task_service.mark_failed.assert_not_awaited()
    dispatcher.enqueue_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_delivery_job_retries_three_times(db_session):
    """投递瞬时失败最多尝试三次，不触发研究执行"""
    delivery_service = AsyncMock()
    delivery_service.deliver.side_effect = [
        RuntimeError("first"),
        RuntimeError("second"),
        None,
    ]
    sleep = AsyncMock()

    await execute_delivery_job(
        "R20260612-ABCDEF12",
        session_factory=_session_factory(db_session),
        delivery_service=delivery_service,
        sleep=sleep,
    )

    assert delivery_service.deliver.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_execute_step_job_uses_persisted_lease_owner(db_session):
    """验证 Worker 沿用调度器持久化的步骤租约；参数为测试会话；无返回值。"""
    step = await _seed_running_step(
        db_session,
        task_id="R-owner",
        owner="dispatch:owner123",
    )
    executor = AsyncMock()
    executor.execute.return_value = SimpleNamespace(success=True, error=None)

    await execute_step_job(
        step.id,
        session_factory=_session_factory(db_session),
        step_service=AsyncMock(),
        executor=executor,
        step_dispatcher=AsyncMock(),
        pipeline=AsyncMock(),
    )

    executor.execute.assert_awaited_once_with(
        db_session,
        step.id,
        "dispatch:owner123",
    )


@pytest.mark.asyncio
async def test_execute_step_job_dispatches_newly_ready_dependencies(db_session):
    """验证步骤提交后继续派发新解锁步骤；参数为测试会话；无返回值。"""
    step = await _seed_running_step(
        db_session,
        task_id="R-next",
        owner="dispatch:next123",
    )
    executor = AsyncMock()
    executor.execute.return_value = SimpleNamespace(success=True, error=None)
    step_dispatcher = AsyncMock()

    await execute_step_job(
        step.id,
        session_factory=_session_factory(db_session),
        step_service=AsyncMock(),
        executor=executor,
        step_dispatcher=step_dispatcher,
        pipeline=AsyncMock(),
    )

    step_dispatcher.dispatch_ready.assert_awaited_once_with("R-next")
