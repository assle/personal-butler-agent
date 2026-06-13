"""研究步骤服务测试"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.models.research import ResearchTask
from src.models.research_execution import ResearchPlan, ResearchStep, ResearchStepDependency
from src.models.workspace import Workspace
from src.research.schemas import ResearchStepStatus
from src.research.steps import ResearchStepService


async def _ensure_workspace(db, ws_id="ws-a"):
    """确保工作空间存在"""
    existing = await db.get(Workspace, ws_id)
    if existing is None:
        ws = Workspace(id=ws_id, name=f"workspace-{ws_id}")
        db.add(ws)
        await db.flush()
    return ws_id


async def _seed_task_and_steps(db, task_id="R1", ws_id="ws-a"):
    """创建测试任务、计划和步骤，返回 (step1, step2)"""
    await _ensure_workspace(db, ws_id)
    task = ResearchTask(
        id=task_id, source_msgid=f"msg-{task_id}",
        requester_open_userid="open-u1", workspace_id=ws_id,
        question="test", research_type="foundation",
        status="submitted", access_scope={}, max_rounds=4,
        timeout_seconds=300, current_round=0, cancel_requested=False,
    )
    db.add(task)
    await db.flush()

    plan = ResearchPlan(
        workspace_id=ws_id, task_id=task_id, version=1,
        objective="test objective",
        completion_criteria=["criterion 1"],
        estimated_cost_microunits=100, estimated_tokens=1000,
        raw_plan={},
    )
    db.add(plan)
    await db.flush()

    # 创建两个步骤，其中 step-2 依赖 step-1
    step1 = ResearchStep(
        id=f"{task_id}:1:a", workspace_id=ws_id, task_id=task_id, plan_id=plan.id,
        kind="test", tool_name="test.tool", input_payload={},
        status=ResearchStepStatus.READY.value, idempotency_key=f"{task_id}:a",
    )
    step2 = ResearchStep(
        id=f"{task_id}:1:b", workspace_id=ws_id, task_id=task_id, plan_id=plan.id,
        kind="test", tool_name="test.tool", input_payload={},
        status=ResearchStepStatus.PENDING.value, idempotency_key=f"{task_id}:b",
    )
    db.add_all([step1, step2])
    await db.flush()
    db.add(ResearchStepDependency(step_id=step2.id, depends_on_step_id=step1.id))
    await db.flush()
    return step1, step2


@pytest.mark.asyncio
async def test_claim_next_returns_ready_step(db_session):
    """验证认领返回且仅返回 ready 状态的步骤"""
    step1, step2 = await _seed_task_and_steps(db_session)
    service = ResearchStepService(lease_seconds=120)
    claimed = await service.claim_next(db_session, owner="worker-a")
    assert len(claimed) == 1
    assert claimed[0].id == step1.id
    assert claimed[0].status == ResearchStepStatus.RUNNING.value
    assert claimed[0].owner == "worker-a"
    assert claimed[0].lease_expires_at is not None


@pytest.mark.asyncio
async def test_complete_step_unblocks_dependent(db_session):
    """验证步骤完成后解除依赖步骤阻塞"""
    step1, step2 = await _seed_task_and_steps(db_session)
    service = ResearchStepService(lease_seconds=120)
    await service.claim_next(db_session, owner="worker-a")
    await service.complete_step(db_session, step1.id)

    # 刷新 step2
    refreshed = await db_session.get(ResearchStep, step2.id)
    assert refreshed.status == ResearchStepStatus.READY.value


@pytest.mark.asyncio
async def test_failed_step_cancels_dependents(db_session):
    """验证步骤失败时取消依赖步骤"""
    step1, step2 = await _seed_task_and_steps(db_session)
    service = ResearchStepService(lease_seconds=120)
    await service.claim_next(db_session, owner="worker-a")
    await service.complete_step(db_session, step1.id, error="tool error")

    refreshed = await db_session.get(ResearchStep, step2.id)
    assert refreshed.status == ResearchStepStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_recover_expired_leases_resets_status(db_session):
    """验证过期租约恢复为 ready 状态"""
    step1, step2 = await _seed_task_and_steps(db_session)
    service = ResearchStepService(lease_seconds=0)  # 立即过期
    await service.claim_next(db_session, owner="worker-a")

    recovered = await service.recover_expired_leases(db_session)
    assert step1.id in recovered
    refreshed = await db_session.get(ResearchStep, step1.id)
    assert refreshed.status == ResearchStepStatus.READY.value
    assert refreshed.owner is None


@pytest.mark.asyncio
async def test_mark_root_steps_ready(db_session):
    """验证无依赖步骤被标记为 ready"""
    await _ensure_workspace(db_session, "ws-a")
    task = ResearchTask(
        id="R-roots", source_msgid="msg-roots",
        requester_open_userid="open-u1", workspace_id="ws-a",
        question="test", research_type="foundation",
        status="submitted", access_scope={}, max_rounds=4,
        timeout_seconds=300, current_round=0, cancel_requested=False,
    )
    db_session.add(task)
    await db_session.flush()

    plan = ResearchPlan(
        workspace_id="ws-a", task_id="R-roots", version=1,
        objective="test objective",
        completion_criteria=["criterion 1"],
        estimated_cost_microunits=100, estimated_tokens=1000,
        raw_plan={},
    )
    db_session.add(plan)
    await db_session.flush()

    step = ResearchStep(
        id="R-roots:1:a", workspace_id="ws-a", task_id="R-roots", plan_id=plan.id,
        kind="test", tool_name="test.tool", input_payload={},
        status=ResearchStepStatus.PENDING.value, idempotency_key="R-roots:a",
    )
    db_session.add(step)
    await db_session.flush()

    service = ResearchStepService()
    count = await service.mark_root_steps_ready(db_session, "R-roots")
    assert count == 1
    refreshed = await db_session.get(ResearchStep, step.id)
    assert refreshed.status == ResearchStepStatus.READY.value
