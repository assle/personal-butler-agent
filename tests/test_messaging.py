"""
消息场景分发测试
验证企业微信回调消息会先被规范化，再交给场景分发层处理。
"""


def test_inbound_message_from_text_callback():
    """验证文本回调会转换为统一入站消息对象"""
    from src.messaging import InboundMessage

    raw = {
        "msgid": "msg-1",
        "msgtype": "text",
        "from": {"userid": "user-a"},
        "text": {"content": "你好"},
        "chattype": "single",
        "response_url": "https://reply.example",
    }

    message = InboundMessage.from_wecom_callback(raw)

    assert message.source == "wecom_callback"
    assert message.msg_id == "msg-1"
    assert message.msg_type == "text"
    assert message.user_id == "user-a"
    assert message.content == "你好"
    assert message.chat_type == "single"
    assert message.chat_id is None
    assert message.response_url == "https://reply.example"
    assert message.raw is raw


def test_inbound_message_from_group_voice_callback():
    """验证语音识别内容会作为统一文本内容进入后续流程"""
    from src.messaging import InboundMessage

    raw = {
        "msgid": "msg-2",
        "msgtype": "voice",
        "from": {"userid": "user-b"},
        "voice": {"content": "总结一下"},
        "chattype": "group",
        "chatid": "chat-1",
        "response_url": "https://reply.example",
    }

    message = InboundMessage.from_wecom_callback(raw)

    assert message.msg_type == "voice"
    assert message.user_id == "user-b"
    assert message.content == "总结一下"
    assert message.chat_type == "group"
    assert message.chat_id == "chat-1"


import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_group_policy_saves_non_trigger_without_reply(db_session):
    """验证群聊普通消息只保存不回复"""
    from sqlalchemy import select

    from src.messaging import InboundMessage, apply_group_policy
    from src.models.group_message import GroupMessage

    message = InboundMessage(
        source="wecom_callback",
        msg_id="msg-3",
        msg_type="text",
        user_id="user-a",
        content="今天接口已经修好了",
        chat_type="group",
        chat_id="chat-1",
        response_url="https://reply.example",
        raw={},
    )

    decision = await apply_group_policy(message, db_session)
    rows = (await db_session.execute(select(GroupMessage))).scalars().all()

    assert decision.should_reply is False
    assert decision.reason == "non_trigger"
    assert len(rows) == 1
    assert rows[0].content == "今天接口已经修好了"


@pytest.mark.asyncio
async def test_group_policy_triggers_summary_after_saving(db_session):
    """验证群聊总结请求会保存并触发回复"""
    from src.messaging import InboundMessage, apply_group_policy

    message = InboundMessage(
        source="wecom_callback",
        msg_id="msg-4",
        msg_type="text",
        user_id="user-a",
        content="总结一下刚才讨论",
        chat_type="group",
        chat_id="chat-1",
        response_url="https://reply.example",
        raw={},
    )

    decision = await apply_group_policy(message, db_session)

    assert decision.should_reply is True
    assert decision.reason == "trigger"
    assert decision.category == "summarize_group"


@pytest.mark.asyncio
async def test_group_policy_classifies_weather_with_domain_name(db_session):
    """验证天气触发分类使用 weather 而不是历史占位名称"""
    from src.messaging import InboundMessage, apply_group_policy

    message = InboundMessage(
        source="wecom_callback",
        msg_id="msg-weather",
        msg_type="text",
        user_id="user-a",
        content="今天上海天气怎么样？",
        chat_type="group",
        chat_id="chat-1",
        response_url="https://reply.example",
        raw={},
    )

    decision = await apply_group_policy(message, db_session)

    assert decision.should_reply is True
    assert decision.category == "weather"


@pytest.mark.asyncio
async def test_group_policy_ignores_empty_voice(db_session):
    """验证空语音识别内容不保存不回复"""
    from src.messaging import InboundMessage, apply_group_policy

    message = InboundMessage(
        source="wecom_callback",
        msg_id="msg-5",
        msg_type="voice",
        user_id="user-a",
        content="",
        chat_type="group",
        chat_id="chat-1",
        response_url="https://reply.example",
        raw={},
    )

    decision = await apply_group_policy(message, db_session)

    assert decision.should_reply is False
    assert decision.reason == "empty_content"


@pytest.mark.asyncio
async def test_dispatch_private_message_to_private_butler(db_session):
    """验证私聊消息进入 PrivateButlerAgent"""
    from src.messaging import InboundMessage, dispatch_message

    private_agent = AsyncMock()
    private_agent.handle.return_value.reply = "私聊回复"
    private_agent.handle.return_value.data = {"intent": "private_butler"}

    result = await dispatch_message(
        InboundMessage(
            source="wecom_callback",
            msg_id="msg-6",
            msg_type="text",
            user_id="user-a",
            content="今天练什么",
            chat_type="single",
            chat_id=None,
            response_url="https://reply.example",
            raw={},
        ),
        db_session,
        private_agent=private_agent,
        group_agent=AsyncMock(),
    )

    assert result.should_reply is True
    assert result.reply == "私聊回复"
    private_agent.handle.assert_awaited_once_with(
        "private_butler",
        "今天练什么",
        "user-a",
        db_session,
        extra_state={"chat_type": "single", "chat_id": None},
    )


@pytest.mark.asyncio
async def test_dispatch_group_non_trigger_does_not_call_agent(db_session):
    """验证群聊非触发消息只保存不调用 agent"""
    from src.messaging import InboundMessage, dispatch_message

    group_agent = AsyncMock()
    result = await dispatch_message(
        InboundMessage(
            source="wecom_callback",
            msg_id="msg-7",
            msg_type="text",
            user_id="user-a",
            content="这个需求我看过了",
            chat_type="group",
            chat_id="chat-1",
            response_url="https://reply.example",
            raw={},
        ),
        db_session,
        private_agent=AsyncMock(),
        group_agent=group_agent,
    )

    assert result.should_reply is False
    assert result.reply == ""
    group_agent.handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_group_trigger_to_group_agent(db_session):
    """验证群聊触发消息进入 GroupMentionAgent"""
    from src.messaging import InboundMessage, dispatch_message

    group_agent = AsyncMock()
    group_agent.handle.return_value.reply = "群聊总结"
    group_agent.handle.return_value.data = {"count": 3}

    result = await dispatch_message(
        InboundMessage(
            source="wecom_callback",
            msg_id="msg-8",
            msg_type="text",
            user_id="user-a",
            content="总结一下",
            chat_type="group",
            chat_id="chat-1",
            response_url="https://reply.example",
            raw={},
        ),
        db_session,
        private_agent=AsyncMock(),
        group_agent=group_agent,
    )

    assert result.should_reply is True
    assert result.reply == "群聊总结"
    group_agent.handle.assert_awaited_once_with(
        "group_mention",
        "总结一下",
        "user-a",
        db_session,
        extra_state={
            "chat_type": "group",
            "chat_id": "chat-1",
            "group_category": "summarize_group",
        },
    )
