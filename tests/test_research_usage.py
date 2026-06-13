"""研究用量测试"""
import pytest

from src.models.research import ResearchTask
from src.models.workspace import Workspace
from src.research.usage import ResearchUsageRecorder


@pytest.mark.asyncio
async def test_usage_recorder_persists_tokens_cost_and_latency(db_session):
    """验证模型与工具用量可累计到任务预算"""
    db_session.add(Workspace(id="ws-a", name="Test Workspace", policy={}))
    await db_session.flush()
    db_session.add(ResearchTask(
        id="R1", source_msgid="msg-1",
        requester_open_userid="open-u1", workspace_id="ws-a",
        question="test", research_type="foundation",
        status="submitted", access_scope={}, max_rounds=4, timeout_seconds=300,
        current_round=0, cancel_requested=False,
    ))
    await db_session.flush()

    usage = await ResearchUsageRecorder().record(
        db_session,
        workspace_id="ws-a",
        task_id="R1",
        step_id="R1:1:web",
        provider="deepseek",
        model="deepseek-chat",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microunits=1200,
        latency_ms=800,
    )
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    totals = await ResearchUsageRecorder().totals(db_session, "ws-a", "R1")
    assert totals.total_tokens == 150
    assert totals.estimated_cost_microunits == 1200
    assert totals.tool_calls == 1


@pytest.mark.asyncio
async def test_usage_totals_zero_for_no_records(db_session):
    """验证无记录时总计为零"""
    totals = await ResearchUsageRecorder().totals(db_session, "ws-a", "nonexistent")
    assert totals.total_tokens == 0
    assert totals.estimated_cost_microunits == 0
    assert totals.tool_calls == 0
