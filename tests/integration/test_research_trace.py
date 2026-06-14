"""
研究链路追踪集成测试
验证 StageRecorder 正确记录阶段开始、完成、失败事件及 trace_id 传播。
"""
from unittest.mock import AsyncMock

import pytest

from src.models.research import ResearchTask
from src.models.workspace import Workspace
from src.research.events import EventWriter
from src.research.observability import StageRecorder, TraceContext


@pytest.fixture
def mock_task_service():
    """提供模拟的 ResearchTaskService"""
    svc = AsyncMock()
    svc.get_task = AsyncMock()

    async def _get_task(db, task_id):
        return await db.get(ResearchTask, task_id)

    svc.get_task.side_effect = _get_task
    return svc


@pytest.mark.asyncio
async def test_trace_context_propagates_task_step_and_attempt():
    """验证 TraceContext 传播任务、步骤和重试信息"""
    ctx = TraceContext(
        trace_id="t1",
        workspace_id="ws-a",
        task_id="R1",
        step_id="R1:1:web",
        attempt=2,
    )
    fields = ctx.as_log_fields()
    assert fields["task_id"] == "R1"
    assert fields["attempt"] == 2


@pytest.mark.asyncio
async def test_stage_recorder_records_started_and_completed(
    db_session, mock_task_service
):
    """验证 StageRecorder 记录开始和完成事件"""
    db_session.add(Workspace(id="ws-trace", name="Trace Workspace", policy={}))
    await db_session.flush()
    db_session.add(
        ResearchTask(
            id="R-trace-1",
            trace_id="trace-001",
            source_msgid="msg-trace-1",
            requester_open_userid="open-u1",
            workspace_id="ws-trace",
            question="test trace",
            research_type="foundation",
            status="submitted",
            access_scope={},
            max_rounds=4,
            timeout_seconds=300,
            current_round=0,
            cancel_requested=False,
        )
    )
    await db_session.flush()

    recorder = StageRecorder(EventWriter(), mock_task_service)
    async with recorder.measure(
        db_session,
        task_id="R-trace-1",
        workspace_id="ws-trace",
        stage="planning",
    ):
        pass

    await db_session.flush()

    # Verify events were appended
    from sqlalchemy import select
    from src.models.research_execution import ResearchEvent

    events = (
        await db_session.execute(
            select(ResearchEvent).where(ResearchEvent.task_id == "R-trace-1")
        )
    ).scalars().all()

    event_types = {e.event_type for e in events}
    assert "stage.started" in event_types
    assert "stage.completed" in event_types

    completed = [e for e in events if e.event_type == "stage.completed"]
    assert len(completed) == 1
    assert completed[0].payload["stage"] == "planning"
    assert completed[0].payload["elapsed_ms"] >= 0
    assert completed[0].trace_id == "trace-001"


@pytest.mark.asyncio
async def test_stage_recorder_records_failed_event(db_session, mock_task_service):
    """验证 StageRecorder 记录失败事件"""
    db_session.add(Workspace(id="ws-trace-2", name="Trace Workspace 2", policy={}))
    await db_session.flush()
    db_session.add(
        ResearchTask(
            id="R-trace-2",
            trace_id="trace-002",
            source_msgid="msg-trace-2",
            requester_open_userid="open-u1",
            workspace_id="ws-trace-2",
            question="test trace fail",
            research_type="foundation",
            status="submitted",
            access_scope={},
            max_rounds=4,
            timeout_seconds=300,
            current_round=0,
            cancel_requested=False,
        )
    )
    await db_session.flush()

    recorder = StageRecorder(EventWriter(), mock_task_service)
    with pytest.raises(RuntimeError, match="stage failed"):
        async with recorder.measure(
            db_session,
            task_id="R-trace-2",
            workspace_id="ws-trace-2",
            stage="execution",
        ):
            raise RuntimeError("stage failed")

    await db_session.flush()

    from sqlalchemy import select
    from src.models.research_execution import ResearchEvent

    events = (
        await db_session.execute(
            select(ResearchEvent).where(ResearchEvent.task_id == "R-trace-2")
        )
    ).scalars().all()

    event_types = {e.event_type for e in events}
    assert "stage.started" in event_types
    assert "stage.failed" in event_types
    assert "stage.completed" not in event_types

    failed = [e for e in events if e.event_type == "stage.failed"]
    assert len(failed) == 1
    assert failed[0].payload["stage"] == "execution"
    assert failed[0].payload["elapsed_ms"] >= 0
    assert failed[0].payload["failure_category"] == "terminal"
    assert failed[0].trace_id == "trace-002"
