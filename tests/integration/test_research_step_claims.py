"""PG 并发步骤认领测试"""
import asyncio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.models.research import ResearchTask
from src.models.research_execution import ResearchPlan, ResearchStep
from src.models.workspace import Workspace
from src.research.steps import ResearchStepService
from src.research.schemas import ResearchStepStatus


async def _ensure_workspace(session, ws_id="ws-a"):
    existing = await session.get(Workspace, ws_id)
    if existing is None:
        session.add(Workspace(id=ws_id, name=f"workspace-{ws_id}", status="active"))
        await session.flush()


async def _seed_two_ready_steps(session):
    await _ensure_workspace(session)
    task = ResearchTask(id="R-conc", source_msgid="msg-conc", requester_open_userid="u1",
        workspace_id="ws-a", question="test", research_type="foundation",
        status="running", access_scope={}, max_rounds=4, timeout_seconds=300,
        current_round=0, cancel_requested=False)
    session.add(task)
    await session.flush()
    plan = ResearchPlan(workspace_id="ws-a", task_id="R-conc", version=1,
        objective="test", completion_criteria=["c1"],
        estimated_cost_microunits=100, estimated_tokens=1000, raw_plan={})
    session.add(plan)
    await session.flush()
    for key in ("a", "b"):
        session.add(ResearchStep(id=f"R-conc:1:{key}", workspace_id="ws-a", task_id="R-conc",
            plan_id=plan.id, kind="test", tool_name="knowledge.search", input_payload={},
            status=ResearchStepStatus.READY.value, idempotency_key=f"R-conc:{key}"))
    await session.flush()


async def _claim_one(session_factory, owner, task_id="R-conc"):
    async with session_factory() as db:
        svc = ResearchStepService(120)
        claimed = await svc.claim_next(db, owner=owner, limit=1, task_id=task_id)
        await db.commit()
        return claimed


@pytest.mark.asyncio
async def test_concurrent_workers_claim_different_steps(postgres_session_factory):
    """验证并发 Worker 不会认领同一步骤"""
    async with postgres_session_factory() as db:
        await _seed_two_ready_steps(db)
        await db.commit()
    a, b = await asyncio.gather(
        _claim_one(postgres_session_factory, "worker-a"),
        _claim_one(postgres_session_factory, "worker-b"),
    )
    assert len(a) == 1 and len(b) == 1
    assert a[0].id != b[0].id


@pytest.mark.asyncio
async def test_single_step_claimed_once(postgres_session_factory):
    """验证单步骤不会被两个 Worker 同时认领"""
    async with postgres_session_factory() as db:
        await _ensure_workspace(db)
        task = ResearchTask(id="R-single", source_msgid="msg-single", requester_open_userid="u1",
            workspace_id="ws-a", question="test", research_type="foundation",
            status="running", access_scope={}, max_rounds=4, timeout_seconds=300,
            current_round=0, cancel_requested=False)
        db.add(task)
        await db.flush()
        plan = ResearchPlan(workspace_id="ws-a", task_id="R-single", version=1,
            objective="test", completion_criteria=["c1"],
            estimated_cost_microunits=100, estimated_tokens=1000, raw_plan={})
        db.add(plan)
        await db.flush()
        db.add(ResearchStep(id="R-single:1:x", workspace_id="ws-a", task_id="R-single",
            plan_id=plan.id, kind="test", tool_name="knowledge.search", input_payload={},
            status=ResearchStepStatus.READY.value, idempotency_key="R-single:x"))
        await db.commit()
    a, b = await asyncio.gather(
        _claim_one(postgres_session_factory, "worker-a", task_id="R-single"),
        _claim_one(postgres_session_factory, "worker-b", task_id="R-single"),
    )
    all_ids = {s.id for claimed in (a, b) for s in claimed}
    assert len(all_ids) == 1
    assert "R-single:1:x" in all_ids
