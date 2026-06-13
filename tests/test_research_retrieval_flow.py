"""
研究检索执行流程测试
验证步骤执行器正确认领、执行工具、持久化证据并更新步骤状态
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.models.research import ResearchTask
from src.models.research_execution import ResearchPlan, ResearchStep
from src.models.workspace import Workspace
from src.research.evidence import ResearchEvidenceService
from src.research.execution import ResearchStepExecutor, StepExecutionResult
from src.research.schemas import ResearchStepStatus
from src.research.steps import ResearchStepService
from src.research.tools.schemas import ToolExecutionResult


async def _seed_deps(db_session, *, ws_id="ws-a", task_id="R1", step_id="R1:1:a"):
    """创建测试所需的 FK 依赖记录

    参数:
        db_session: 异步数据库会话
        ws_id: 工作空间 ID
        task_id: 研究任务 ID
        step_id: 步骤 ID
    """
    existing_ws = await db_session.get(Workspace, ws_id)
    if existing_ws is None:
        db_session.add(Workspace(id=ws_id, name=f"workspace-{ws_id}"))
        await db_session.flush()

    existing_task = await db_session.get(ResearchTask, task_id)
    if existing_task is None:
        db_session.add(ResearchTask(
            id=task_id, source_msgid=f"msg-{task_id}",
            requester_open_userid="open-u1", workspace_id=ws_id,
            question="test", research_type="foundation",
            status="running", access_scope={}, max_rounds=4,
            timeout_seconds=300, current_round=0, cancel_requested=False,
        ))
        await db_session.flush()

    from sqlalchemy import select

    existing_plan = (await db_session.execute(
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
        db_session.add(plan)
        await db_session.flush()
        existing_plan = plan

    existing_step = await db_session.get(ResearchStep, step_id)
    if existing_step is None:
        db_session.add(ResearchStep(
            id=step_id, workspace_id=ws_id, task_id=task_id,
            plan_id=existing_plan.id,
            kind="knowledge", tool_name="knowledge.search",
            input_payload={"query": "test"},
            status=ResearchStepStatus.RUNNING.value,
            idempotency_key=step_id, owner=f"worker:{step_id}",
        ))
        await db_session.flush()


@pytest.mark.asyncio
async def test_executor_persists_evidence_and_completes_step(db_session):
    """验证步骤执行后证据被持久化且步骤完成"""
    await _seed_deps(db_session)

    # Mock 工具返回证据
    registry = AsyncMock()
    registry.execute.return_value = ToolExecutionResult(
        success=True,
        data={
            "summary": "found",
            "evidence": [{
                "workspace_id": "ws-a", "task_id": "R1", "step_id": "R1:1:a",
                "source_type": "web", "source_ref": "http://example.com",
                "title": "Test", "publisher": None, "published_at": None,
                "retrieved_at": "2024-01-01T00:00:00Z",
                "excerpt": "content", "query": "test query",
                "confidence": None, "metadata": {},
            }],
        },
    )

    evidence_service = ResearchEvidenceService()
    step_service = ResearchStepService(lease_seconds=120)

    executor = ResearchStepExecutor(
        registry=registry, evidence_service=evidence_service,
        step_service=step_service,
    )
    result = await executor.execute(db_session, "R1:1:a", "worker:R1:1:a")

    assert result.success is True
    assert len(result.evidence_ids) == 1
    assert result.result_ref == f"evidence:{result.evidence_ids[0]}"

    # 验证步骤状态已更新
    step = await db_session.get(ResearchStep, "R1:1:a")
    assert step.status == ResearchStepStatus.COMPLETED.value
    assert step.result_ref == result.result_ref


@pytest.mark.asyncio
async def test_executor_handles_tool_failure_gracefully(db_session):
    """验证工具失败时步骤被标记为失败"""
    await _seed_deps(db_session, ws_id="ws-fail", task_id="R-fail",
                     step_id="R-fail:1:a")

    registry = AsyncMock()
    registry.execute.return_value = ToolExecutionResult(
        success=False, error="timeout",
    )

    executor = ResearchStepExecutor(
        registry=registry, evidence_service=ResearchEvidenceService(),
        step_service=ResearchStepService(lease_seconds=120),
    )
    result = await executor.execute(db_session, "R-fail:1:a", "worker:R-fail:1:a")
    assert result.success is False
    assert result.error == "timeout"

    # 验证步骤状态已更新
    step = await db_session.get(ResearchStep, "R-fail:1:a")
    assert step.status == ResearchStepStatus.FAILED.value
    assert step.error == "timeout"


@pytest.mark.asyncio
async def test_executor_rejects_wrong_owner(db_session):
    """验证步骤不属于当前 Worker 时返回错误"""
    await _seed_deps(db_session, ws_id="ws-own", task_id="R-own",
                     step_id="R-own:1:a")

    registry = AsyncMock()
    executor = ResearchStepExecutor(
        registry=registry, evidence_service=ResearchEvidenceService(),
        step_service=ResearchStepService(lease_seconds=120),
    )
    result = await executor.execute(db_session, "R-own:1:a", "worker:other")
    assert result.success is False
    assert "不属于当前 Worker" in result.error
    registry.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_executor_handles_missing_step(db_session):
    """验证不存在的步骤返回错误"""
    executor = ResearchStepExecutor(
        registry=AsyncMock(), evidence_service=ResearchEvidenceService(),
        step_service=ResearchStepService(lease_seconds=120),
    )
    result = await executor.execute(db_session, "nonexistent", "worker:x")
    assert result.success is False
    assert "步骤不存在" in result.error
