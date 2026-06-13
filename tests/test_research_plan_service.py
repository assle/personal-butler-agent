"""研究计划持久化测试"""
import pytest
from sqlalchemy import select

from src.models.research import ResearchTask
from src.models.research_execution import ResearchPlan, ResearchStep, ResearchStepDependency
from src.models.workspace import Workspace
from src.research.planning.schemas import PlanDraft, StepDraft
from src.research.planning.service import PlanService


def _valid_draft() -> PlanDraft:
    return PlanDraft(
        objective="compare",
        completion_criteria=["cost", "performance"],
        estimated_tokens=1000,
        estimated_cost_microunits=100,
        steps=[
            StepDraft(key="a", kind="knowledge", tool_name="knowledge.search", input_payload={}),
            StepDraft(key="b", kind="web", tool_name="web.search", input_payload={}, depends_on=["a"]),
        ],
    )


@pytest.mark.asyncio
async def test_persist_plan_creates_versioned_steps_and_dependencies(db_session):
    """验证计划、步骤和依赖在同一事务中持久化"""
    # 创建工作空间和任务
    db_session.add(Workspace(id="ws-a", name="Test Workspace", policy={}))
    await db_session.flush()
    db_session.add(ResearchTask(
        id="R20240101-TEST0001", source_msgid="msg-p1",
        requester_open_userid="open-u1", workspace_id="ws-a",
        question="test", research_type="foundation",
        status="submitted", access_scope={}, max_rounds=4, timeout_seconds=300,
        current_round=0, cancel_requested=False,
    ))
    await db_session.flush()

    plan = await PlanService().persist(
        db_session, workspace_id="ws-a", task_id="R20240101-TEST0001",
        draft=_valid_draft(),
    )
    assert plan.version == 1

    step_result = await db_session.execute(
        select(ResearchStep).where(ResearchStep.task_id == "R20240101-TEST0001")
    )
    steps = step_result.scalars().all()
    assert len(steps) == 2

    dep_result = await db_session.execute(
        select(ResearchStepDependency)
    )
    deps = dep_result.scalars().all()
    assert len(deps) == 1


@pytest.mark.asyncio
async def test_persist_plan_increments_version_on_second_draft(db_session):
    """验证同一任务重新规划时版本号递增"""
    db_session.add(Workspace(id="ws-b", name="Test Workspace", policy={}))
    await db_session.flush()
    db_session.add(ResearchTask(
        id="R20240101-TEST0002", source_msgid="msg-p2",
        requester_open_userid="open-u1", workspace_id="ws-b",
        question="test", research_type="foundation",
        status="submitted", access_scope={}, max_rounds=4, timeout_seconds=300,
        current_round=0, cancel_requested=False,
    ))
    await db_session.flush()

    draft = _valid_draft()
    svc = PlanService()

    plan1 = await svc.persist(db_session, workspace_id="ws-b", task_id="R20240101-TEST0002", draft=draft)
    assert plan1.version == 1

    plan2 = await svc.persist(db_session, workspace_id="ws-b", task_id="R20240101-TEST0002", draft=draft)
    assert plan2.version == 2

    # 验证步骤 ID 包含版本号
    step_result = await db_session.execute(
        select(ResearchStep).where(ResearchStep.task_id == "R20240101-TEST0002")
    )
    step_ids = [s.id for s in step_result.scalars().all()]
    assert any(":1:" in sid for sid in step_ids)
    assert any(":2:" in sid for sid in step_ids)
