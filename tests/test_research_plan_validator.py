"""研究计划校验器测试"""
import pytest

from src.research.planning.schemas import PlanDraft, StepDraft
from src.research.planning.validator import (
    BudgetLimits,
    PlanValidationError,
    PlanValidator,
)


def _valid_draft() -> PlanDraft:
    """创建合法计划草案的辅助函数"""
    return PlanDraft(
        objective="compare solutions",
        completion_criteria=["cover cost"],
        estimated_tokens=1000,
        estimated_cost_microunits=100,
        steps=[
            StepDraft(
                key="a", kind="knowledge_retrieval",
                tool_name="knowledge.search", input_payload={},
            ),
            StepDraft(
                key="b", kind="web_retrieval",
                tool_name="web.search", input_payload={},
                depends_on=["a"],
            ),
        ],
    )


def test_validator_rejects_cycle():
    """验证循环依赖被拒绝"""
    draft = PlanDraft(
        objective="compare",
        completion_criteria=["cover cost"],
        estimated_tokens=1000,
        estimated_cost_microunits=100,
        steps=[
            StepDraft(
                key="a", kind="knowledge_retrieval",
                tool_name="knowledge.search", input_payload={},
                depends_on=["b"],
            ),
            StepDraft(
                key="b", kind="web_retrieval",
                tool_name="web.search", input_payload={},
                depends_on=["a"],
            ),
        ],
    )
    with pytest.raises(PlanValidationError, match="循环"):
        PlanValidator(allowed_tools={"knowledge.search", "web.search"}).validate(
            draft, limits=BudgetLimits.default(),
        )


def test_validator_rejects_unknown_tool():
    """验证未知工具被拒绝"""
    draft = _valid_draft()
    draft.steps[0].tool_name = "unknown.tool"
    with pytest.raises(PlanValidationError, match="未注册"):
        PlanValidator(allowed_tools={"web.search"}).validate(
            draft, limits=BudgetLimits.default(),
        )


def test_validator_rejects_self_dependency():
    """验证自依赖被拒绝"""
    draft = PlanDraft(
        objective="test",
        completion_criteria=["x"],
        estimated_tokens=10,
        estimated_cost_microunits=10,
        steps=[
            StepDraft(
                key="a", kind="test", tool_name="web.search",
                input_payload={}, depends_on=["a"],
            ),
        ],
    )
    with pytest.raises(PlanValidationError, match="自身"):
        PlanValidator(allowed_tools={"web.search"}).validate(
            draft, limits=BudgetLimits.default(),
        )


def test_validator_rejects_missing_dependency():
    """验证引用不存在的步骤被拒绝"""
    draft = _valid_draft()
    draft.steps[0].depends_on = ["nonexistent"]
    with pytest.raises(PlanValidationError, match="不存在"):
        PlanValidator(allowed_tools={"knowledge.search", "web.search"}).validate(
            draft, limits=BudgetLimits.default(),
        )


def test_validator_rejects_duplicate_keys():
    """验证重复 key 被拒绝"""
    draft = PlanDraft(
        objective="test",
        completion_criteria=["x"],
        estimated_tokens=10,
        estimated_cost_microunits=10,
        steps=[
            StepDraft(key="a", kind="x", tool_name="web.search", input_payload={}),
            StepDraft(key="a", kind="y", tool_name="web.search", input_payload={}),
        ],
    )
    with pytest.raises(PlanValidationError, match="唯一"):
        PlanValidator(allowed_tools={"web.search"}).validate(
            draft, limits=BudgetLimits.default(),
        )


def test_validator_rejects_budget_step_overflow():
    """验证步骤数超限被拒绝"""
    draft = PlanDraft(
        objective="test", completion_criteria=["x"],
        estimated_tokens=10, estimated_cost_microunits=10,
        steps=[
            StepDraft(key=str(i), kind="x", tool_name="web.search", input_payload={})
            for i in range(13)
        ],
    )
    with pytest.raises(PlanValidationError, match="步骤数"):
        PlanValidator(allowed_tools={"web.search"}).validate(
            draft, limits=BudgetLimits(max_steps=12),
        )


def test_validator_accepts_valid_plan():
    """验证合法计划通过所有校验"""
    PlanValidator(allowed_tools={"knowledge.search", "web.search"}).validate(
        _valid_draft(), limits=BudgetLimits.default(),
    )
