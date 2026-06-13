"""研究事件测试"""
import pytest

from src.models.research import ResearchTask
from src.models.workspace import Workspace
from src.research.events import EventWriter


@pytest.mark.asyncio
async def test_event_writer_redacts_secret_fields(db_session):
    """验证事件载荷不保存密钥和访问令牌"""
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

    event = await EventWriter().append(
        db_session,
        workspace_id="ws-a",
        task_id="R1",
        event_type="tool.called",
        payload={"api_key": "secret", "query": "safe"},
    )
    assert event.payload == {"api_key": "[REDACTED]", "query": "safe"}


@pytest.mark.asyncio
async def test_event_writer_preserves_nested_safe_fields(db_session):
    """验证嵌套结构中的安全字段保留，敏感字段脱敏"""
    db_session.add(Workspace(id="ws-b", name="Test Workspace", policy={}))
    await db_session.flush()
    db_session.add(ResearchTask(
        id="R2", source_msgid="msg-2",
        requester_open_userid="open-u1", workspace_id="ws-b",
        question="test", research_type="foundation",
        status="submitted", access_scope={}, max_rounds=4, timeout_seconds=300,
        current_round=0, cancel_requested=False,
    ))
    await db_session.flush()

    event = await EventWriter().append(
        db_session, workspace_id="ws-b", task_id="R2",
        event_type="test",
        payload={"config": {"token": "x", "timeout": 30}},
    )
    assert event.payload == {"config": {"token": "[REDACTED]", "timeout": 30}}


@pytest.mark.asyncio
async def test_event_writer_empty_payload_is_safe(db_session):
    """验证空载荷写入不报错"""
    db_session.add(Workspace(id="ws-c", name="Test Workspace", policy={}))
    await db_session.flush()
    db_session.add(ResearchTask(
        id="R3", source_msgid="msg-3",
        requester_open_userid="open-u1", workspace_id="ws-c",
        question="test", research_type="foundation",
        status="submitted", access_scope={}, max_rounds=4, timeout_seconds=300,
        current_round=0, cancel_requested=False,
    ))
    await db_session.flush()

    event = await EventWriter().append(
        db_session, workspace_id="ws-c", task_id="R3",
        event_type="test",
    )
    assert event.payload == {}
