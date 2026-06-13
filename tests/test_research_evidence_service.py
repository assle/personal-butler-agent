"""研究证据服务测试"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from src.models.research import ResearchTask
from src.models.research_execution import ResearchPlan, ResearchStep
from src.models.workspace import Workspace
from src.research.evidence import EvidenceInput, ResearchEvidenceService
from src.models.research_evidence import ResearchEvidence


async def _seed_deps(db, *, ws_id="ws-a", task_id="R1", step_id="R1:1:a"):
    """创建测试所需的 FK 依赖记录（工作空间、任务、计划、步骤）

    参数:
        db: 异步数据库会话
        ws_id: 工作空间 ID
        task_id: 研究任务 ID
        step_id: 步骤 ID
    """
    # 工作空间
    existing_ws = await db.get(Workspace, ws_id)
    if existing_ws is None:
        db.add(Workspace(id=ws_id, name=f"workspace-{ws_id}"))
        await db.flush()

    # 研究任务
    existing_task = await db.get(ResearchTask, task_id)
    if existing_task is None:
        db.add(ResearchTask(
            id=task_id, source_msgid=f"msg-{task_id}",
            requester_open_userid="open-u1", workspace_id=ws_id,
            question="test", research_type="foundation",
            status="submitted", access_scope={}, max_rounds=4,
            timeout_seconds=300, current_round=0, cancel_requested=False,
        ))
        await db.flush()

    # 计划（步骤依赖计划的整数 PK）
    existing_plan = (await db.execute(
        select(ResearchPlan).where(
            ResearchPlan.task_id == task_id,
            ResearchPlan.workspace_id == ws_id,
        )
    )).scalar_one_or_none()
    if existing_plan is None:
        plan = ResearchPlan(
            workspace_id=ws_id, task_id=task_id, version=1,
            objective="test objective",
            completion_criteria=["criterion 1"],
            estimated_cost_microunits=100, estimated_tokens=1000,
            raw_plan={},
        )
        db.add(plan)
        await db.flush()
        existing_plan = plan

    # 步骤
    existing_step = await db.get(ResearchStep, step_id)
    if existing_step is None:
        db.add(ResearchStep(
            id=step_id, workspace_id=ws_id, task_id=task_id,
            plan_id=existing_plan.id,
            kind="test", tool_name="test.tool", input_payload={},
            status="completed", idempotency_key=step_id,
        ))
        await db.flush()


def _evidence_input(workspace_id="ws-a", task_id="R1", step_id="R1:1:a",
                    source_ref="http://example.com/1",
                    excerpt="test excerpt") -> EvidenceInput:
    """创建标准测试证据输入"""
    return EvidenceInput(
        workspace_id=workspace_id,
        task_id=task_id,
        step_id=step_id,
        source_type="web",
        source_ref=source_ref,
        title="Test Evidence",
        publisher="Test Publisher",
        retrieved_at=datetime.now(timezone.utc),
        excerpt=excerpt,
        query="test query",
        confidence=0.9,
    )


@pytest.mark.asyncio
async def test_evidence_is_deduplicated_by_workspace_and_content_hash(db_session):
    """验证同工作空间相同来源片段只保存一次"""
    await _seed_deps(db_session)
    service = ResearchEvidenceService()
    first = await service.store(db_session, _evidence_input())
    second = await service.store(db_session, _evidence_input())
    assert second.id == first.id


@pytest.mark.asyncio
async def test_same_hash_different_workspace_is_isolated(db_session):
    """验证不同工作空间的证据不会互相复用"""
    await _seed_deps(db_session, ws_id="ws-a")
    await _seed_deps(db_session, ws_id="ws-b", task_id="R2", step_id="R2:1:a")
    service = ResearchEvidenceService()
    first = await service.store(
        db_session, _evidence_input(task_id="R1"))
    second = await service.store(
        db_session, _evidence_input(
            workspace_id="ws-b", task_id="R2", step_id="R2:1:a"))
    assert second.id != first.id


@pytest.mark.asyncio
async def test_list_by_task_returns_all_evidence(db_session):
    """验证按任务查询返回全部证据"""
    await _seed_deps(db_session, task_id="R1", step_id="R1:1:a")
    await _seed_deps(db_session, task_id="R1", step_id="R1:1:b")
    await _seed_deps(db_session, task_id="R2", step_id="R2:1:a")

    service = ResearchEvidenceService()
    await service.store(db_session, _evidence_input(task_id="R1", step_id="R1:1:a"))
    await service.store(
        db_session, _evidence_input(
            task_id="R1", step_id="R1:1:b",
            source_ref="http://example.com/2", excerpt="other"))
    await service.store(
        db_session, _evidence_input(
            task_id="R2", step_id="R2:1:a",
            source_ref="http://example.com/3", excerpt="another"))

    r1_evidence = await service.list_by_task(db_session, "R1")
    assert len(r1_evidence) == 2
    r2_evidence = await service.list_by_task(db_session, "R2")
    assert len(r2_evidence) == 1
