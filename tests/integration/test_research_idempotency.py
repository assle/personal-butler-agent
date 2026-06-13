"""阶段幂等测试"""
import asyncio
import pytest
from src.models.research import ResearchTask, ResearchReport, ResearchDelivery
from src.models.research_execution import ResearchPlan, ResearchStep
from src.models.workspace import Workspace
from src.research.schemas import ResearchTaskStatus, ResearchStepStatus
from src.research.pipeline import ResearchPipelineCoordinator
from src.research.service import ResearchTaskService
from unittest.mock import AsyncMock


async def _ensure_workspace_and_plan(session, ws_id="ws-a", task_id="R-idem2"):
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
async def test_concurrent_synthesis_is_idempotent(postgres_session):
    """验证并发综合检查只创建一份报告"""
    plan_id = await _ensure_workspace_and_plan(postgres_session)
    step = ResearchStep(id="R-idem2:1:a", workspace_id="ws-a", task_id="R-idem2", plan_id=plan_id,
        kind="test", tool_name="knowledge.search", input_payload={},
        status=ResearchStepStatus.COMPLETED.value, idempotency_key="R-idem2:a")
    postgres_session.add(step)
    await postgres_session.flush()

    ts = ResearchTaskService(4, 300)
    synth = AsyncMock()
    synth.enqueue_synthesis = AsyncMock()
    coord = ResearchPipelineCoordinator(task_service=ts, dispatcher=AsyncMock(),
        synthesis_dispatcher=synth, validation_dispatcher=AsyncMock(),
        delivery_dispatcher=AsyncMock(), step_dispatcher=AsyncMock())

    r1, r2 = await asyncio.gather(
        coord.queue_synthesis_if_complete(postgres_session, "R-idem2"),
        coord.queue_synthesis_if_complete(postgres_session, "R-idem2"),
    )
    assert sum([r1, r2]) == 1  # One succeeded, one duplicate
    synth.enqueue_synthesis.assert_awaited_once()
