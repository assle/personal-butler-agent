"""Supervisor 规划测试"""
from unittest.mock import AsyncMock
import pytest
from src.research.planning.schemas import PlanDraft, StepDraft
from src.research.planning.validator import PlanValidator
from src.research.supervisor.planner import TaskSnapshot
from src.research.supervisor.service import ResearchSupervisor


def _valid_draft():
    return PlanDraft(
        objective="research",
        completion_criteria=["done"],
        estimated_tokens=100,
        estimated_cost_microunits=100,
        steps=[
            StepDraft(key="a", kind="knowledge", tool_name="knowledge.search", input_payload={}),
        ],
    )


@pytest.mark.asyncio
async def test_supervisor_generates_and_validates_plan():
    """验证 Supervisor 输出经过本地校验后才持久化"""
    from src.research.approvals import ApprovalPolicy

    llm = AsyncMock()
    llm.ainvoke_structured.return_value = _valid_draft()
    plan_service = AsyncMock()
    task_service = AsyncMock()

    supervisor = ResearchSupervisor(
        llm=llm,
        validator=PlanValidator({"knowledge.search"}),
        plan_service=plan_service,
        approval_policy=ApprovalPolicy(250_000),
    )
    result = await supervisor.plan(
        AsyncMock(),
        TaskSnapshot(task_id="R1", workspace_id="ws-a", question="test", user_id="u1"),
        task_service,
    )
    assert result.plan.objective == "research"
    llm.ainvoke_structured.assert_awaited_once()
    plan_service.persist.assert_awaited_once()
