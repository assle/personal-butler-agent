"""
Taskiq 核心任务函数测试
不连接 Redis，验证研究、超时、失败和独立投递重试。
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from src.research.tasks import execute_delivery_job, execute_research_job


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
