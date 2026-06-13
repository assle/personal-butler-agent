"""研究执行失败分类"""
from dataclasses import dataclass
from enum import StrEnum


class FailureCategory(StrEnum):
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    PROVIDER_5XX = "provider_5xx"
    CONTEXT_OVERFLOW = "context_overflow"
    SOURCE_UNAVAILABLE = "source_unavailable"
    PERMISSION = "permission"
    INVALID_INPUT = "invalid_input"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class FailureDecision:
    category: FailureCategory
    retryable: bool
    retry_after_seconds: float | None = None
    degrade_provider: bool = False


def classify_error(error: Exception) -> FailureDecision:
    """将异常映射为失败分类和重试建议"""
    name = type(error).__name__
    msg = str(error).lower()

    if "timeout" in name.lower() or "timeout" in msg:
        return FailureDecision(FailureCategory.NETWORK, True)
    if "429" in msg or "rate" in msg or "throttl" in msg:
        return FailureDecision(FailureCategory.RATE_LIMIT, True)
    if "503" in msg or "502" in msg or "500" in msg or "server error" in msg:
        return FailureDecision(FailureCategory.PROVIDER_5XX, True, degrade_provider=True)
    if "context" in msg and ("overflow" in msg or "too long" in msg or "exceed" in msg):
        return FailureDecision(FailureCategory.CONTEXT_OVERFLOW, True)
    if "permission" in msg or "denied" in msg or "forbidden" in msg:
        return FailureDecision(FailureCategory.PERMISSION, False)
    if "invalid" in msg or "bad" in msg or "argument" in msg:
        return FailureDecision(FailureCategory.INVALID_INPUT, False)
    return FailureDecision(FailureCategory.TERMINAL, False)
