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


@pytest.mark.asyncio
async def test_supervisor_removes_pipeline_only_steps_before_validation():
    """验证综合等管线步骤不会作为工具步骤持久化；无参数；无返回值。"""
    from src.research.approvals import ApprovalPolicy

    draft = PlanDraft(
        objective="research",
        completion_criteria=["done"],
        estimated_tokens=100,
        estimated_cost_microunits=100,
        steps=[
            StepDraft(
                key="search",
                kind="web_retrieval",
                tool_name="web.search",
                input_payload={"query": "Self-Refine Reflexion"},
            ),
            StepDraft(
                key="synthesize",
                kind="synthesis",
                tool_name="",
                input_payload={},
                depends_on=["search"],
            ),
        ],
    )
    llm = AsyncMock()
    llm.ainvoke_structured.return_value = draft
    plan_service = AsyncMock()
    task_service = AsyncMock()
    supervisor = ResearchSupervisor(
        llm=llm,
        validator=PlanValidator({"web.search"}),
        plan_service=plan_service,
        approval_policy=ApprovalPolicy(250_000),
    )

    result = await supervisor.plan(
        AsyncMock(),
        TaskSnapshot(task_id="R2", workspace_id="ws-a", question="test", user_id="u1"),
        task_service,
    )

    assert [step.key for step in result.plan.steps] == ["search"]
    persisted_draft = plan_service.persist.await_args.kwargs["draft"]
    assert [step.key for step in persisted_draft.steps] == ["search"]


@pytest.mark.asyncio
async def test_supervisor_skips_first_use_approval_for_preapproved_member():
    """验证已完成首次审批的成员可直接运行低成本计划；无参数；无返回值。"""
    from src.research.approvals import ApprovalPolicy
    from src.research.schemas import ResearchTaskStatus

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
        TaskSnapshot(
            task_id="R3",
            workspace_id="ws-a",
            question="test",
            user_id="u1",
            research_approved_once=True,
        ),
        task_service,
    )

    assert result.requires_approval is False
    assert task_service.transition.await_args_list[-1].kwargs["target"] == (
        ResearchTaskStatus.RUNNING
    )


@pytest.mark.asyncio
async def test_supervisor_creates_first_use_approval_record():
    """验证首次研究通过审批服务创建待审批记录；无参数；无返回值。"""
    from src.research.approvals import ApprovalPolicy

    llm = AsyncMock()
    llm.ainvoke_structured.return_value = _valid_draft()
    plan = AsyncMock()
    plan.estimated_cost_microunits = 100
    plan_service = AsyncMock()
    plan_service.persist.return_value = plan
    task = AsyncMock()
    task_service = AsyncMock()
    task_service.get_task.return_value = task
    approval_service = AsyncMock()
    supervisor = ResearchSupervisor(
        llm=llm,
        validator=PlanValidator({"knowledge.search"}),
        plan_service=plan_service,
        approval_policy=ApprovalPolicy(250_000),
        approval_service=approval_service,
    )

    result = await supervisor.plan(
        AsyncMock(),
        TaskSnapshot(
            task_id="R4",
            workspace_id="ws-a",
            question="test",
            user_id="u1",
            member_id=7,
            role="member",
            research_approved_once=False,
        ),
        task_service,
    )

    assert result.requires_approval is True
    approval_service.request_approval.assert_awaited_once()
