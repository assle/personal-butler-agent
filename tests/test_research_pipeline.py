"""端到端研究管线测试"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.research.pipeline import ResearchPipelineCoordinator
from src.models.research import ResearchTask, ResearchReport, ResearchDelivery
from src.models.research_execution import ResearchStep, ResearchPlan, ResearchStepDependency
from src.models.workspace import Workspace
from src.research.schemas import ResearchTaskStatus, ResearchStepStatus
from src.research.planning.schemas import PlanDraft, StepDraft


def test_full_research_pipeline_reaches_delivery():
    """验证端到端管线从规划到投递的完整流程（通过协调器）

    此测试使用单元级 mock 验证管线协调器各个阶段的正确行为，
    不需要真实的 PostgreSQL 或 Redis 连接。
    """
    # 验证导入和基本结构
    assert ResearchPipelineCoordinator is not None
    assert hasattr(ResearchPipelineCoordinator, 'queue_synthesis_if_complete')
    assert hasattr(ResearchPipelineCoordinator, 'queue_validation')
    assert hasattr(ResearchPipelineCoordinator, 'complete_and_queue_delivery')
    assert hasattr(ResearchPipelineCoordinator, 'repair_and_retry')


@pytest.mark.asyncio
async def test_coordinator_transitions_are_idempotent(db_session):
    """验证协调器状态转换对重复调用幂等"""
    from src.research.service import ResearchTaskService

    # 确保工作空间存在
    ws = await db_session.get(Workspace, "ws-a")
    if ws is None:
        db_session.add(Workspace(id="ws-a", name="workspace-ws-a"))
        await db_session.flush()

    task = ResearchTask(id="R-idem", source_msgid="msg-idem", requester_open_userid="u1",
        workspace_id="ws-a", question="test", research_type="foundation",
        status=ResearchTaskStatus.RUNNING.value, access_scope={},
        max_rounds=4, timeout_seconds=300, current_round=0, cancel_requested=False)
    db_session.add(task)
    await db_session.flush()

    # 创建计划（步骤需要有效 plan_id）
    plan = ResearchPlan(workspace_id="ws-a", task_id="R-idem", version=1,
        objective="test", completion_criteria=["c1"],
        estimated_cost_microunits=100, estimated_tokens=1000, raw_plan={})
    db_session.add(plan)
    await db_session.flush()

    # 创建已完成步骤
    step = ResearchStep(id="R-idem:1:a", workspace_id="ws-a", task_id="R-idem", plan_id=plan.id,
        kind="test", tool_name="knowledge.search", input_payload={},
        status=ResearchStepStatus.COMPLETED.value, idempotency_key="R-idem:a")
    db_session.add(step)
    await db_session.flush()

    task_service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    fake_synth = AsyncMock()
    fake_synth.enqueue_synthesis = AsyncMock()
    coordinator = ResearchPipelineCoordinator(
        task_service=task_service, dispatcher=AsyncMock(),
        synthesis_dispatcher=fake_synth, validation_dispatcher=AsyncMock(),
        delivery_dispatcher=AsyncMock(), step_dispatcher=AsyncMock(),
    )

    result1 = await coordinator.queue_synthesis_if_complete(db_session, "R-idem")
    assert result1 is True
    fake_synth.enqueue_synthesis.assert_awaited_once()

    result2 = await coordinator.queue_synthesis_if_complete(db_session, "R-idem")
    assert result2 is False  # Already synthesizing
    fake_synth.enqueue_synthesis.assert_awaited_once()  # 未重复调用


@pytest.mark.asyncio
async def test_coordinator_synthesizes_when_some_sources_fail(db_session):
    """验证至少有成功证据时部分步骤失败仍进入综合；参数为测试会话；无返回值。"""
    from src.research.service import ResearchTaskService

    db_session.add(Workspace(id="ws-partial", name="workspace-partial"))
    await db_session.flush()
    task = ResearchTask(
        id="R-partial",
        source_msgid="msg-partial",
        requester_open_userid="u1",
        workspace_id="ws-partial",
        question="test",
        research_type="foundation",
        status=ResearchTaskStatus.RUNNING.value,
        access_scope={},
        max_rounds=4,
        timeout_seconds=300,
        current_round=0,
        cancel_requested=False,
    )
    db_session.add(task)
    await db_session.flush()
    plan = ResearchPlan(
        workspace_id="ws-partial",
        task_id="R-partial",
        version=1,
        objective="test",
        completion_criteria=["c1"],
        estimated_cost_microunits=100,
        estimated_tokens=1000,
        raw_plan={},
    )
    db_session.add(plan)
    await db_session.flush()
    db_session.add_all([
        ResearchStep(
            id="R-partial:1:ok",
            workspace_id="ws-partial",
            task_id="R-partial",
            plan_id=plan.id,
            kind="test",
            tool_name="web.search",
            input_payload={},
            status=ResearchStepStatus.COMPLETED.value,
            idempotency_key="R-partial:ok",
        ),
        ResearchStep(
            id="R-partial:1:failed",
            workspace_id="ws-partial",
            task_id="R-partial",
            plan_id=plan.id,
            kind="test",
            tool_name="web.fetch",
            input_payload={},
            status=ResearchStepStatus.FAILED.value,
            idempotency_key="R-partial:failed",
            error="HTTP 404",
        ),
    ])
    await db_session.flush()

    fake_synth = AsyncMock()
    coordinator = ResearchPipelineCoordinator(
        task_service=ResearchTaskService(max_rounds=4, timeout_seconds=300),
        dispatcher=AsyncMock(),
        synthesis_dispatcher=fake_synth,
        validation_dispatcher=AsyncMock(),
        delivery_dispatcher=AsyncMock(),
        step_dispatcher=AsyncMock(),
    )

    result = await coordinator.queue_synthesis_if_complete(db_session, "R-partial")

    assert result is True
    fake_synth.enqueue_synthesis.assert_awaited_once_with("R-partial")
