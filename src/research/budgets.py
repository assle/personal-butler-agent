"""研究预算与用量跟踪"""
from dataclasses import dataclass
from enum import StrEnum


class BudgetState(StrEnum):
    """研究预算状态"""
    AVAILABLE = "available"
    SOFT_LIMIT = "soft_limit"
    HARD_LIMIT = "hard_limit"


@dataclass(frozen=True)
class BudgetLimits:
    """研究预算限制"""
    max_tokens: int = 20_000
    soft_tokens: int = 15_000
    max_cost_microunits: int = 500_000
    soft_cost_microunits: int = 350_000
    max_steps: int = 12
    max_concurrent_steps: int = 3
    max_replans: int = 2
    max_repair_rounds: int = 1

    @classmethod
    def default(cls) -> "BudgetLimits":
        """返回默认预算限制"""
        return cls()


class BudgetExceededError(RuntimeError):
    """预算超限"""


@dataclass
class ResearchBudget:
    """可变的运行时预算跟踪器"""

    limits: BudgetLimits
    _tokens: int = 0
    _cost_microunits: int = 0

    def record(self, *, tokens: int = 0, cost_microunits: int = 0) -> None:
        """记录用量；超出硬限制时抛出 BudgetExceededError

        参数:
            tokens: 新增 token 数
            cost_microunits: 新增微单位成本数

        异常:
            BudgetExceededError: 超过硬限制
        """
        self._tokens += tokens
        self._cost_microunits += cost_microunits

        if (self._tokens > self.limits.max_tokens
                or self._cost_microunits > self.limits.max_cost_microunits):
            raise BudgetExceededError(
                f"预算硬限制已达到: tokens={self._tokens}/{self.limits.max_tokens}, "
                f"cost={self._cost_microunits}/{self.limits.max_cost_microunits}"
            )

    @property
    def state(self) -> BudgetState:
        """返回当前预算状态"""
        if (self._tokens >= self.limits.max_tokens
                or self._cost_microunits >= self.limits.max_cost_microunits):
            return BudgetState.HARD_LIMIT
        if (self._tokens >= self.limits.soft_tokens
                or self._cost_microunits >= self.limits.soft_cost_microunits):
            return BudgetState.SOFT_LIMIT
        return BudgetState.AVAILABLE

    @property
    def total_tokens(self) -> int:
        """已消耗 token 总数"""
        return self._tokens

    @property
    def total_cost_microunits(self) -> int:
        """已消耗微单位成本总数"""
        return self._cost_microunits
