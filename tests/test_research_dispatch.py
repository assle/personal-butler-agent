"""研究步骤派发测试"""
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from src.models.research import ResearchTask
from src.models.research_execution import ResearchPlan, ResearchStep, ResearchStepDependency
from src.models.workspace import Workspace
from src.research.schemas import ResearchStepStatus
from src.research.steps import ResearchStepService
from src.research.dispatch import ResearchStepDispatcher


async def _ensure_workspace(db, ws_id="ws-a"):
    existing = await db.get(Workspace, ws_id)
    if existing is None:
        db.add(Workspace(id=ws_id, name=f"workspace-{ws_id}"))
        await db.flush()
    return ws_id


async def _seed_ready_step(db, step_id="R1:1:a", task_id="R1", ws_id="ws-a"):
    await _ensure_workspace(db, ws_id)
    task = ResearchTask(id=task_id, source_msgid=f"msg-{step_id}", requester_open_userid="u1",
        workspace_id=ws_id, question="test", research_type="foundation",
        status="running", access_scope={}, max_rounds=4, timeout_seconds=300,
        current_round=0, cancel_requested=False)
    db.add(task)
    await db.flush()
    plan = ResearchPlan(workspace_id=ws_id, task_id=task_id, version=1,
        objective="test", completion_criteria=["c1"],
        estimated_cost_microunits=100, estimated_tokens=1000, raw_plan={})
    db.add(plan)
    await db.flush()
    step = ResearchStep(id=step_id, workspace_id=ws_id, task_id=task_id, plan_id=plan.id,
        kind="test", tool_name="knowledge.search", input_payload={"query": "x"},
        status=ResearchStepStatus.READY.value, idempotency_key=f"{task_id}:a")
    db.add(step)
    await db.flush()
    return step


@pytest.mark.asyncio
async def test_dispatch_ready_claims_before_enqueue(db_session):
    """验证步骤先持久化认领，再发送到队列"""
    await _seed_ready_step(db_session)
    fake_queue = AsyncMock()
    fake_queue.enqueue_step = AsyncMock()
    dispatcher = ResearchStepDispatcher(
        ResearchStepService(120), fake_queue, lambda: db_session, max_concurrent=3)
    count = await dispatcher.dispatch_ready(task_id="R1")
    assert count == 1
    refreshed = await db_session.get(ResearchStep, "R1:1:a")
    assert refreshed.status == ResearchStepStatus.RUNNING.value
    fake_queue.enqueue_step.assert_awaited_once_with("R1:1:a")


@pytest.mark.asyncio
async def test_enqueue_failure_releases_claim(db_session):
    """验证队列发送失败后步骤恢复为 ready"""
    await _seed_ready_step(db_session)
    fake_queue = AsyncMock()
    fake_queue.enqueue_step = AsyncMock(side_effect=RuntimeError("redis down"))
    dispatcher = ResearchStepDispatcher(
        ResearchStepService(120), fake_queue, lambda: db_session, max_concurrent=3)
    with pytest.raises(RuntimeError, match="redis down"):
        await dispatcher.dispatch_ready(task_id="R1")
    refreshed = await db_session.get(ResearchStep, "R1:1:a")
    assert refreshed.status == ResearchStepStatus.READY.value
    assert refreshed.owner is None
