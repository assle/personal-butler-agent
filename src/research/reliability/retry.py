"""研究步骤重试策略"""
import random


class RetryPolicy:
    def __init__(self, base_seconds: float = 1.0, max_seconds: float = 30.0, jitter_ratio: float = 0.1):
        self._base = base_seconds
        self._max = max_seconds
        self._jitter = jitter_ratio

    def delay(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return float(retry_after)
        delay = min(self._base * (2 ** (attempt - 1)), self._max)
        jitter = delay * self._jitter * random.random()
        return delay + jitter
