"""Redis 支持的提供者熔断器"""
import logging
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

class ProviderCircuitBreaker:
    def __init__(self, redis: Redis, *, failure_threshold: int = 3, open_seconds: int = 60):
        self._redis = redis
        self._threshold = failure_threshold
        self._open_seconds = open_seconds

    def _failure_key(self, provider: str) -> str:
        return f"research:circuit:{provider}:failures"

    def _open_key(self, provider: str) -> str:
        return f"research:circuit:{provider}:open"

    async def record_failure(self, provider: str) -> None:
        key = self._failure_key(provider)
        count = await self._redis.incr(key)
        await self._redis.expire(key, self._open_seconds * 2)
        if count >= self._threshold:
            await self._redis.setex(self._open_key(provider), self._open_seconds, "1")
            logger.warning("Circuit OPEN for %s after %d failures", provider, count)

    async def record_success(self, provider: str) -> None:
        await self._redis.delete(self._failure_key(provider))

    async def allow(self, provider: str) -> bool:
        return not await self._redis.exists(self._open_key(provider))

    async def reset(self, provider: str) -> None:
        await self._redis.delete(self._failure_key(provider), self._open_key(provider))
