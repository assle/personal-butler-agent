"""PG 恢复集成测试"""
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from src.models.research import ResearchTask
from src.models.research_execution import ResearchPlan, ResearchStep
from src.models.workspace import Workspace
from src.research.schemas import ResearchStepStatus


async def _ensure_workspace_and_plan(session, ws_id="ws-a", task_id="R-rec"):
    existing_ws = await session.get(Workspace, ws_id)
    if existing_ws is None:
        session.add(Workspace(id=ws_id, name=f"workspace-{ws_id}", status="active"))
        await session.flush()
    task = ResearchTask(id=task_id, source_msgid=f"msg-{task_id}", requester_open_userid="u1",
        workspace_id=ws_id, question="test", research_type="foundation",
        status="running", access_scope={}, max_rounds=4, timeout_seconds=300,
        current_round=0, cancel_requested=False)
    session.add(task)
    await session.flush()
    plan = ResearchPlan(workspace_id=ws_id, task_id=task_id, version=1,
        objective="test", completion_criteria=["c1"],
        estimated_cost_microunits=100, estimated_tokens=1000, raw_plan={})
    session.add(plan)
    await session.flush()
    return plan.id


@pytest.mark.asyncio
async def test_expired_lease_recovers_and_claims(postgres_session):
    """验证过期租约恢复后通过 dispatcher 重新认领"""
    plan_id = await _ensure_workspace_and_plan(postgres_session)
    step = ResearchStep(id="R-rec:1:a", workspace_id="ws-a", task_id="R-rec", plan_id=plan_id,
        kind="test", tool_name="knowledge.search", input_payload={},
        status=ResearchStepStatus.RUNNING.value, idempotency_key="R-rec:a",
        owner="dead-worker", lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=60))
    postgres_session.add(step)
    await postgres_session.flush()

    from src.research.steps import ResearchStepService
    svc = ResearchStepService(120)
    recovered = await svc.recover_expired_leases(postgres_session, limit=100)
    assert step.id in recovered
    refreshed = await postgres_session.get(ResearchStep, step.id)
    assert refreshed.status == ResearchStepStatus.READY.value
    assert refreshed.owner is None
