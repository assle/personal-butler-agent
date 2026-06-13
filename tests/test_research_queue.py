"""
研究任务队列适配器测试
验证应用层只依赖 enqueue 接口，不依赖 Taskiq 返回结果。
"""
from unittest.mock import AsyncMock

import pytest

from src.research.queue import TaskiqResearchDispatcher


@pytest.mark.asyncio
async def test_dispatcher_enqueues_research_task():
    """研究 dispatcher 调用 Taskiq task 的 kiq"""
    run_task = AsyncMock()
    dispatcher = TaskiqResearchDispatcher(run_task=run_task, deliver_task=AsyncMock())
    await dispatcher.enqueue_research("R20260612-ABCDEF12")
    run_task.kiq.assert_awaited_once_with("R20260612-ABCDEF12")


@pytest.mark.asyncio
async def test_dispatcher_enqueues_delivery_separately():
    """报告投递使用独立 Taskiq task"""
    deliver = AsyncMock()
    dispatcher = TaskiqResearchDispatcher(
        run_task=AsyncMock(), deliver_task=deliver
    )
    await dispatcher.enqueue_delivery("R20260612-ABCDEF12")
    deliver.kiq.assert_awaited_once_with("R20260612-ABCDEF12")


@pytest.mark.asyncio
async def test_dispatcher_enqueues_planning_task():
    """研究规划使用独立 plan task"""
    plan = AsyncMock()
    dispatcher = TaskiqResearchDispatcher(
        run_task=AsyncMock(), deliver_task=AsyncMock(),
        plan_task=plan,
    )
    await dispatcher.enqueue_planning("R20260612-ABCDEF12")
    plan.kiq.assert_awaited_once_with("R20260612-ABCDEF12")


@pytest.mark.asyncio
async def test_dispatcher_enqueues_step():
    """步骤执行使用独立 step task"""
    step = AsyncMock()
    dispatcher = TaskiqResearchDispatcher(
        run_task=AsyncMock(), deliver_task=AsyncMock(),
        step_task=step,
    )
    await dispatcher.enqueue_step("step-123")
    step.kiq.assert_awaited_once_with("step-123")
