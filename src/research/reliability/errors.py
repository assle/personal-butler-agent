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
    """将异常映射为失败分类和重试建议

    优先级：异常类型层级检查优先于字符串匹配，避免误分类。
    字符串匹配作为自定义异常（如 FakePermission）的 fallback。
    """
    import asyncio

    # 类型层级检查（优先于字符串匹配）
    if isinstance(error, asyncio.TimeoutError):
        return FailureDecision(FailureCategory.NETWORK, True)

    name = type(error).__name__
    msg = str(error).lower()

    # 异常类名匹配真实标准异常
    if "PermissionError" in name or "Forbidden" in name or name == "PermissionError":
        return FailureDecision(FailureCategory.PERMISSION, False)
    if "ValueError" in name or "TypeError" in name or "AssertionError" in name:
        return FailureDecision(FailureCategory.INVALID_INPUT, False)

    # 字符串匹配（传输层和限流错误，以及自定义异常 fallback）
    if "429" in msg or "rate" in msg or "throttl" in msg:
        return FailureDecision(FailureCategory.RATE_LIMIT, True)
    if "503" in msg or "502" in msg:
        return FailureDecision(FailureCategory.PROVIDER_5XX, True, degrade_provider=True)
    if "timeout" in msg:
        return FailureDecision(FailureCategory.NETWORK, True)
    if "context" in msg and ("overflow" in msg or "too long" in msg):
        return FailureDecision(FailureCategory.CONTEXT_OVERFLOW, True)
    if "permission" in msg or "denied" in msg or "forbidden" in msg:
        return FailureDecision(FailureCategory.PERMISSION, False)
    if "invalid" in msg or "bad argument" in msg:
        return FailureDecision(FailureCategory.INVALID_INPUT, False)

    return FailureDecision(FailureCategory.TERMINAL, False)
