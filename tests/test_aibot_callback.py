"""
智能机器人 URL 回调测试
验证加密回调解析、入站消息幂等落库，以及 response_url 被动回复流程
"""
import base64
import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select


@pytest.fixture
def mock_intent_router():
    """创建测试用意图路由器

    返回:
        AsyncMock: route() 固定返回 qa 意图
    """
    router = AsyncMock()
    router.route.return_value = ("qa", 0.9)
    return router


@pytest.fixture
def mock_agent_registry():
    """创建测试用 agent 注册表

    返回:
        AgentRegistry: 注册了 qa 和 summarize_group 的测试注册表
    """
    from src.agents.registry import AgentRegistry
    from src.schemas.response import AgentResponse

    registry = AgentRegistry()
    mock_agent = AsyncMock()
    mock_agent.handle.return_value = AgentResponse(reply="mock reply")
    registry.register("qa", mock_agent)
    registry.register("summarize_group", mock_agent)
    return registry


def _valid_encoding_aes_key() -> str:
    """生成测试用 43 位 EncodingAESKey

    返回:
        str: 去掉末尾等号的 Base64 AES key
    """
    return base64.b64encode(b"1" * 32).decode().rstrip("=")


def test_callback_crypto_decrypts_echo_string():
    """验证 URL 校验 echostr 可以通过签名校验并解密

    返回:
        None
    """
    from src.wechat.callback_crypto import WeComCallbackCrypto

    crypto = WeComCallbackCrypto(
        token="token-1",
        encoding_aes_key=_valid_encoding_aes_key(),
        receive_id="bot-1",
    )
    encrypted = crypto.encrypt("hello", "123", "nonce-1")

    plain = crypto.decrypt_if_signature_valid(
        signature=encrypted.signature,
        timestamp="123",
        nonce="nonce-1",
        encrypt_text=encrypted.encrypt,
    )

    assert plain == "hello"


@pytest.mark.asyncio
async def test_record_inbound_message_is_idempotent(db_session):
    """验证同一 msgid 的回调只入库一次，避免企微重试导致重复处理

    参数:
        db_session: 测试数据库会话
    """
    from src.models.inbound_message import InboundMessage
    from src.wechat.callback_inbox import record_inbound_message

    msg = {
        "msgid": "msg-dup",
        "aibotid": "bot-1",
        "msgtype": "text",
        "from": {"userid": "user1"},
        "text": {"content": "你好"},
        "chattype": "single",
        "response_url": "https://example.test/respond",
    }

    first = await record_inbound_message(db_session, msg)
    second = await record_inbound_message(db_session, msg)

    await db_session.commit()
    rows = (await db_session.execute(select(InboundMessage))).scalars().all()
    assert first.should_process is True
    assert second.should_process is False
    assert len(rows) == 1
    assert rows[0].msgid == "msg-dup"
    assert rows[0].status == "pending"


@pytest.mark.asyncio
async def test_handle_callback_message_posts_reply_to_response_url(
    db_session,
    mock_intent_router,
    mock_agent_registry,
):
    """验证 URL 回调消息处理完成后通过 response_url 回复

    参数:
        db_session: 测试数据库会话
        mock_intent_router: 模拟意图路由器
        mock_agent_registry: 模拟 agent 注册表
    """
    from src.wechat.callback_handler import ResponseUrlReplyClient, handle_callback_message

    posted = []

    async def fake_post_json(url: str, payload: dict) -> bool:
        """记录待发送的 response_url 请求

        参数:
            url: 企业微信回调里的临时回复 URL
            payload: 要发送的消息体

        返回:
            bool: 模拟发送成功
        """
        posted.append((url, payload))
        return True

    reply_client = ResponseUrlReplyClient(post_json=fake_post_json)
    msg = {
        "msgid": "msg-1",
        "aibotid": "bot-1",
        "msgtype": "text",
        "from": {"userid": "user1"},
        "text": {"content": "今天练什么"},
        "chattype": "single",
        "response_url": "https://example.test/respond",
    }

    await handle_callback_message(
        msg,
        reply_client,
        mock_intent_router,
        mock_agent_registry,
        db_session,
    )

    assert posted == [
        (
            "https://example.test/respond",
            {"msgtype": "markdown", "markdown": {"content": "mock reply"}},
        )
    ]


@pytest.mark.asyncio
async def test_callback_router_accepts_encrypted_json_and_records_message(db_session):
    """验证 HTTP 回调路由可以解密 JSON 帧并先落库再返回 success

    参数:
        db_session: 测试数据库会话
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.models.inbound_message import InboundMessage
    from src.wechat.callback_crypto import WeComCallbackCrypto
    from src.wechat.callback_router import create_aibot_callback_router

    async def db_session_factory():
        """返回测试数据库会话

        返回:
            AsyncSession: 当前测试会话
        """
        return db_session

    app = FastAPI()
    app.include_router(
        create_aibot_callback_router(
            token="token-1",
            encoding_aes_key=_valid_encoding_aes_key(),
            receive_id="bot-1",
            intent_router=AsyncMock(),
            agent_registry=AsyncMock(),
            db_session_factory=db_session_factory,
            reply_client=AsyncMock(),
        )
    )
    crypto = WeComCallbackCrypto("token-1", _valid_encoding_aes_key(), "bot-1")
    frame = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-1"},
        "body": {
            "msgid": "msg-http-1",
            "aibotid": "bot-1",
            "msgtype": "text",
            "from": {"userid": "user1"},
            "text": {"content": "你好"},
            "chattype": "single",
            "response_url": "https://example.test/respond",
        },
    }
    encrypted = crypto.encrypt(json.dumps(frame, ensure_ascii=False), "123", "nonce-1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/wechat/aibot/callback",
            params={
                "msg_signature": encrypted.signature,
                "timestamp": "123",
                "nonce": "nonce-1",
            },
            json={"encrypt": encrypted.encrypt},
        )

    await db_session.commit()
    rows = (await db_session.execute(select(InboundMessage))).scalars().all()
    assert response.status_code == 200
    assert response.json() == {"errcode": 0, "errmsg": "ok"}
    assert [row.msgid for row in rows] == ["msg-http-1"]


@pytest.mark.asyncio
async def test_callback_router_accepts_message_when_crypto_receive_id_differs_from_bot_id(db_session):
    """验证智能机器人用消息体 aibotid 校验 BotID，而不把密文尾部 receive_id 当 BotID

    参数:
        db_session: 测试数据库会话
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.models.inbound_message import InboundMessage
    from src.wechat.callback_crypto import WeComCallbackCrypto
    from src.wechat.callback_router import create_aibot_callback_router

    async def db_session_factory():
        """返回测试数据库会话

        返回:
            AsyncSession: 当前测试会话
        """
        return db_session

    app = FastAPI()
    app.include_router(
        create_aibot_callback_router(
            token="token-1",
            encoding_aes_key=_valid_encoding_aes_key(),
            receive_id="bot-1",
            intent_router=AsyncMock(),
            agent_registry=AsyncMock(),
            db_session_factory=db_session_factory,
            reply_client=AsyncMock(),
        )
    )
    crypto = WeComCallbackCrypto("token-1", _valid_encoding_aes_key(), "not-bot-tail")
    frame = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-tail"},
        "body": {
            "msgid": "msg-tail-1",
            "aibotid": "bot-1",
            "msgtype": "text",
            "from": {"userid": "user1"},
            "text": {"content": "你好"},
            "chattype": "single",
            "response_url": "https://example.test/respond",
        },
    }
    encrypted = crypto.encrypt(json.dumps(frame, ensure_ascii=False), "123", "nonce-1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/wechat/aibot/callback",
            params={
                "msg_signature": encrypted.signature,
                "timestamp": "123",
                "nonce": "nonce-1",
            },
            json={"encrypt": encrypted.encrypt},
        )

    await db_session.commit()
    rows = (await db_session.execute(select(InboundMessage))).scalars().all()
    assert response.status_code == 200
    assert [row.msgid for row in rows] == ["msg-tail-1"]
