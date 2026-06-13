"""看门狗测试"""
from unittest.mock import AsyncMock
import pytest
from src.research.reliability.watchdog import ResearchWatchdog


@pytest.mark.asyncio
async def test_watchdog_recovers_expired_and_dispatches():
    steps = AsyncMock()
    steps.recover_expired_leases.return_value = ["s1", "s2"]
    steps.promote_due_retries.return_value = 0
    dispatcher = AsyncMock()
    dispatcher.dispatch_ready.return_value = 2
    tasks = AsyncMock()
    watchdog = ResearchWatchdog(steps, dispatcher, tasks)
    result = await watchdog.run_once(AsyncMock())
    assert result["recovered"] == 2
    assert result["retried"] == 0
    assert result["dispatched"] == 2
    dispatcher.dispatch_ready.assert_awaited_once()


@pytest.mark.asyncio
async def test_watchdog_does_not_dispatch_when_nothing_recovered():
    steps = AsyncMock()
    steps.recover_expired_leases.return_value = []
    steps.promote_due_retries.return_value = 0
    dispatcher = AsyncMock()
    tasks = AsyncMock()
    watchdog = ResearchWatchdog(steps, dispatcher, tasks)
    result = await watchdog.run_once(AsyncMock())
    assert result["recovered"] == 0
    assert result["retried"] == 0
    dispatcher.dispatch_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_watchdog_promotes_retries():
    steps = AsyncMock()
    steps.recover_expired_leases.return_value = []
    steps.promote_due_retries.return_value = 3
    dispatcher = AsyncMock()
    dispatcher.dispatch_ready.return_value = 3
    tasks = AsyncMock()
    watchdog = ResearchWatchdog(steps, dispatcher, tasks)
    result = await watchdog.run_once(AsyncMock())
    assert result["retried"] == 3
    assert result["dispatched"] == 3
    dispatcher.dispatch_ready.assert_awaited_once()
