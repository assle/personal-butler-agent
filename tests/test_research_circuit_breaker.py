"""熔断器测试"""
import pytest
from unittest.mock import AsyncMock
from src.research.reliability.circuit import ProviderCircuitBreaker

@pytest.fixture
def fake_redis():
    redis = AsyncMock()
    redis.incr.return_value = 1
    redis.exists.return_value = 0
    return redis

@pytest.mark.asyncio
async def test_circuit_opens_after_consecutive_failures(fake_redis):
    breaker = ProviderCircuitBreaker(fake_redis, failure_threshold=3, open_seconds=60)
    fake_redis.incr.return_value = 3
    await breaker.record_failure("tavily")
    fake_redis.exists.return_value = 1
    assert await breaker.allow("tavily") is False

@pytest.mark.asyncio
async def test_circuit_allows_after_success(fake_redis):
    breaker = ProviderCircuitBreaker(fake_redis)
    await breaker.record_success("tavily")
    assert await breaker.allow("tavily") is True
