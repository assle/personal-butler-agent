"""重试策略测试"""
import pytest
from src.research.reliability.errors import FailureCategory, classify_error
from src.research.reliability.retry import RetryPolicy


class FakeTimeout(Exception): pass
class FakeRateLimit(Exception): pass
class FakePermission(Exception): pass

@pytest.mark.parametrize("error,category,retryable", [
    (FakeTimeout("timeout"), "network", True),
    (FakeRateLimit("429 too many"), "rate_limit", True),
    (FakePermission("permission denied"), "permission", False),
    (ValueError("bad argument"), "invalid_input", False),
])
def test_error_classifier(error, category, retryable):
    d = classify_error(error)
    assert d.category == category
    assert d.retryable == retryable

def test_retry_delay_uses_retry_after():
    policy = RetryPolicy(base_seconds=1, max_seconds=30, jitter_ratio=0)
    assert policy.delay(attempt=2, retry_after=7) == 7

def test_retry_delay_exponential_backoff():
    policy = RetryPolicy(base_seconds=1, max_seconds=30, jitter_ratio=0)
    assert policy.delay(attempt=2, retry_after=None) == 2
    assert policy.delay(attempt=4, retry_after=None) == 8
