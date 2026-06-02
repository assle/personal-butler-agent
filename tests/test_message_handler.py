"""
消息处理器测试
测试 handle_ws_message 的消息分发逻辑
"""
import pytest
from unittest.mock import AsyncMock


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.send_reply.return_value = True
    return ws


@pytest.fixture
def mock_intent_router():
    router = AsyncMock()
    router.route.return_value = ("qa", 0.9)
    return router


@pytest.fixture
def mock_agent_registry():
    from src.agents.registry import AgentRegistry
    from src.schemas.response import AgentResponse
    registry = AgentRegistry()
    mock_agent = AsyncMock()
    mock_agent.handle.return_value = AgentResponse(reply="mock reply")
    registry.register("qa", mock_agent)
    registry.register("summarize_group", mock_agent)
    return registry


@pytest.mark.asyncio
async def test_handle_private_message(db_session, mock_ws, mock_intent_router, mock_agent_registry):
    """验证私聊消息走意图路由 → agent → 回复"""
    from src.wechat.message_handler import handle_ws_message

    msg = {
        "msgid": "msg-1",
        "msgtype": "text",
        "from": {"userid": "user1"},
        "text": {"content": "今天练什么"},
        "chattype": "single",
    }

    await handle_ws_message(msg, "req-1", mock_ws, mock_intent_router, mock_agent_registry, db_session)

    mock_intent_router.route.assert_called_once_with("今天练什么")
    mock_ws.send_reply.assert_called_once_with("req-1", "mock reply")


@pytest.mark.asyncio
async def test_handle_group_trigger_message(db_session, mock_ws, mock_intent_router, mock_agent_registry):
    """验证群聊触发消息走 summarize_group → 回复"""
    from src.wechat.message_handler import handle_ws_message

    msg = {
        "msgid": "msg-2",
        "msgtype": "text",
        "from": {"userid": "user2"},
        "text": {"content": "群里总结一下"},
        "chattype": "group",
        "chatid": "chat-1",
    }

    await handle_ws_message(msg, "req-2", mock_ws, mock_intent_router, mock_agent_registry, db_session)

    mock_ws.send_reply.assert_called_once()
    # 验证群聊消息被保存
    from src.models.group_message import GroupMessage
    from sqlalchemy import select
    stmt = select(GroupMessage).where(GroupMessage.chat_id == "chat-1")
    result = await db_session.execute(stmt)
    records = result.scalars().all()
    assert len(records) == 1


@pytest.mark.asyncio
async def test_handle_group_non_trigger(db_session, mock_ws, mock_intent_router, mock_agent_registry):
    """验证非触发群聊消息不回复"""
    from src.wechat.message_handler import handle_ws_message

    msg = {
        "msgid": "msg-3",
        "msgtype": "text",
        "from": {"userid": "user3"},
        "text": {"content": "今天天气不错"},
        "chattype": "group",
        "chatid": "chat-2",
    }

    await handle_ws_message(msg, "req-3", mock_ws, mock_intent_router, mock_agent_registry, db_session)

    # 非触发消息不应回复
    mock_ws.send_reply.assert_not_called()


@pytest.mark.asyncio
async def test_handle_voice_message(db_session, mock_ws, mock_intent_router, mock_agent_registry):
    """验证语音消息提取 recognition 文本"""
    from src.wechat.message_handler import handle_ws_message

    msg = {
        "msgid": "msg-4",
        "msgtype": "voice",
        "from": {"userid": "user1"},
        "voice": {"content": "今天练胸"},
        "chattype": "single",
    }

    await handle_ws_message(msg, "req-4", mock_ws, mock_intent_router, mock_agent_registry, db_session)

    mock_intent_router.route.assert_called_once_with("今天练胸")
    mock_ws.send_reply.assert_called_once()


@pytest.mark.asyncio
async def test_handle_voice_empty(db_session, mock_ws, mock_intent_router, mock_agent_registry):
    """验证空语音识别结果静默忽略"""
    from src.wechat.message_handler import handle_ws_message

    msg = {
        "msgid": "msg-5",
        "msgtype": "voice",
        "from": {"userid": "user1"},
        "voice": {"content": ""},
        "chattype": "single",
    }

    await handle_ws_message(msg, "req-5", mock_ws, mock_intent_router, mock_agent_registry, db_session)

    mock_ws.send_reply.assert_not_called()


@pytest.mark.asyncio
async def test_non_text_message(db_session, mock_ws, mock_intent_router, mock_agent_registry):
    """验证非文本非语音消息返回不支持"""
    from src.wechat.message_handler import handle_ws_message

    msg = {
        "msgid": "msg-6",
        "msgtype": "image",
        "from": {"userid": "user1"},
        "chattype": "single",
    }

    await handle_ws_message(msg, "req-6", mock_ws, mock_intent_router, mock_agent_registry, db_session)

    mock_ws.send_reply.assert_called_once()
    args = mock_ws.send_reply.call_args
    assert "暂不支持" in args.args[1]
