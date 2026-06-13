"""研究预算测试"""
import pytest
from src.research.budgets import (
    BudgetExceededError,
    BudgetLimits,
    BudgetState,
    ResearchBudget,
)


def test_budget_classifies_soft_and_hard_limits():
    """验证软硬预算边界"""
    budget = ResearchBudget(
        limits=BudgetLimits(
            max_tokens=20_000,
            soft_tokens=15_000,
            max_cost_microunits=500_000,
            soft_cost_microunits=350_000,
            max_steps=12,
            max_concurrent_steps=3,
            max_replans=2,
            max_repair_rounds=1,
        )
    )
    assert budget.state == BudgetState.AVAILABLE
    budget.record(tokens=15_001)
    assert budget.state == BudgetState.SOFT_LIMIT
    budget.record(cost_microunits=500_000)
    assert budget.state == BudgetState.HARD_LIMIT


def test_budget_raises_on_hard_limit_overrun():
    """验证超出硬限制抛出异常"""
    budget = ResearchBudget(
        limits=BudgetLimits(
            max_tokens=100, soft_tokens=50,
            max_cost_microunits=1000, soft_cost_microunits=500,
            max_steps=5, max_concurrent_steps=2,
            max_replans=1, max_repair_rounds=1,
        )
    )
    budget.record(tokens=100)  # 达到硬限制
    with pytest.raises(BudgetExceededError):
        budget.record(tokens=1)


def test_budget_starts_available():
    """验证新预算初始状态为可用"""
    budget = ResearchBudget(limits=BudgetLimits.default())
    assert budget.state == BudgetState.AVAILABLE
    assert budget.total_tokens == 0
    assert budget.total_cost_microunits == 0


def test_cost_only_soft_limit():
    """验证仅成本达到软限制"""
    budget = ResearchBudget(
        limits=BudgetLimits(
            max_tokens=20_000, soft_tokens=15_000,
            max_cost_microunits=500_000, soft_cost_microunits=350_000,
            max_steps=12, max_concurrent_steps=3,
            max_replans=2, max_repair_rounds=1,
        )
    )
    budget.record(cost_microunits=350_000)
    assert budget.state == BudgetState.SOFT_LIMIT
