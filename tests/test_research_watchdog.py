"""看门狗测试"""
from unittest.mock import AsyncMock
import pytest
from src.research.reliability.watchdog import ResearchWatchdog

@pytest.mark.asyncio
async def test_watchdog_recovers_expired_and_requeues():
    steps = AsyncMock()
    steps.recover_expired_leases.return_value = ["s1", "s2"]
    dispatcher = AsyncMock()
    tasks = AsyncMock()
    watchdog = ResearchWatchdog(steps, dispatcher, tasks)
    result = await watchdog.run_once(AsyncMock())
    assert result["recovered"] == 2
    assert dispatcher.enqueue_step.call_count == 2
