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
    task = AsyncMock()
    dispatcher = TaskiqResearchDispatcher(research_task=task, delivery_task=AsyncMock())
    await dispatcher.enqueue_research("R20260612-ABCDEF12")
    task.kiq.assert_awaited_once_with("R20260612-ABCDEF12")


@pytest.mark.asyncio
async def test_dispatcher_enqueues_delivery_separately():
    """报告投递使用独立 Taskiq task"""
    delivery = AsyncMock()
    dispatcher = TaskiqResearchDispatcher(
        research_task=AsyncMock(), delivery_task=delivery
    )
    await dispatcher.enqueue_delivery("R20260612-ABCDEF12")
    delivery.kiq.assert_awaited_once_with("R20260612-ABCDEF12")
