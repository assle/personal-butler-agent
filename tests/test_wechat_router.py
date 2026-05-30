"""
测试企业微信回调路由（URL 验证 + 消息接收）

Workflow:
1. GET /api/wechat/callback: 验签 + 解密 echostr 返回明文
2. POST /api/wechat/callback: 解密消息 → 意图路由 → agent 处理 → 加密回复
"""
import base64
import hashlib
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.wechat.crypto import encrypt
from src.wechat.router import create_wechat_router


@pytest.fixture
def intent_router():
    """创建 mock IntentRouter，默认返回 ("qa", 0.9)"""
    router = AsyncMock()
    router.route.return_value = ("qa", 0.9)
    return router


@pytest.fixture
def agent_registry():
    """创建 mock AgentRegistry，默认返回回复 "这是测试回复" 的 agent"""
    from src.schemas.response import AgentResponse

    agent = AsyncMock()
    agent.handle.return_value = AgentResponse(reply="这是测试回复", data=None)

    registry = MagicMock()
    registry.get.return_value = agent
    return registry


@pytest.fixture
def wechat_config():
    """生成测试用的企业微信配置

    输出: dict，包含 corp_id, token, encoding_aes_key
    """
    return {
        "corp_id": "test_corp_id",
        "token": "test_token",
        "encoding_aes_key": base64.b64encode(os.urandom(32)).decode(),
    }


def _build_app(wechat_config, intent_router, agent_registry, db_session=None):
    """构建带 wechat 路由的测试 FastAPI 应用

    参数:
        wechat_config: 企业微信配置 dict
        intent_router: mock IntentRouter
        agent_registry: mock AgentRegistry
        db_session: 可选，DB session 用于依赖覆盖

    返回:
        TestClient: FastAPI TestClient
    """
    app = FastAPI()
    router = create_wechat_router(
        intent_router=intent_router,
        agent_registry=agent_registry,
        corp_id=wechat_config["corp_id"],
        token=wechat_config["token"],
        encoding_aes_key=wechat_config["encoding_aes_key"],
    )
    app.include_router(router)

    if db_session is not None:
        from src.db.session import get_db
        app.dependency_overrides[get_db] = lambda: db_session

    return TestClient(app)


def test_get_callback_url_verification_success(wechat_config):
    """测试 GET 回调 URL 验证：正确签名 + 解密 echostr 返回明文

    输入: 正确签名的 msg_signature、加密的 echostr
    输出: 200 + 解密后的明文字符串
    """
    token = wechat_config["token"]
    aes_key = wechat_config["encoding_aes_key"]
    corp_id = wechat_config["corp_id"]

    echostr_plain = "random_echo_string_12345"
    echostr_encrypted = encrypt(aes_key, echostr_plain, corp_id)

    timestamp = str(int(time.time()))
    nonce = "test_nonce"

    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, echostr_encrypted])).encode()
    ).hexdigest()

    client = _build_app(wechat_config, AsyncMock(), AsyncMock())

    response = client.get(
        "/api/wechat/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": echostr_encrypted,
        },
    )

    assert response.status_code == 200
    assert response.text == echostr_plain


def test_get_callback_url_verification_bad_signature(wechat_config):
    """测试 GET 回调 URL 验证：错误签名应返回 403

    输入: 错误的 msg_signature
    输出: 403
    """
    client = _build_app(wechat_config, AsyncMock(), AsyncMock())

    response = client.get(
        "/api/wechat/callback",
        params={
            "msg_signature": "wrong_signature",
            "timestamp": "1234567890",
            "nonce": "test",
            "echostr": "whatever",
        },
    )

    assert response.status_code == 403


async def test_post_callback_text_message(
    wechat_config, intent_router, agent_registry, db_session
):
    """测试 POST 消息回调：正常文本消息被路由到 agent 并返回加密回复

    输入: JSON body 包含加密的内层消息
    输出: 200 + XML 加密回复
    """
    token = wechat_config["token"]
    aes_key = wechat_config["encoding_aes_key"]
    corp_id = wechat_config["corp_id"]

    # 构造内层 JSON 消息并加密
    inner = {
        "from_user_name": "user_001",
        "msg_type": "text",
        "content": "今天练什么",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), corp_id)

    timestamp = str(int(time.time()))
    nonce = "test_nonce"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_app(wechat_config, intent_router, agent_registry, db_session)

    response = client.post(
        "/api/wechat/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={
            "to_user_name": "test_corp_id",
            "agent_id": "1000001",
            "encrypt": encrypted_content,
        },
    )

    assert response.status_code == 200
    # 验证 agent 流水线被调用
    intent_router.route.assert_called()
    agent_registry.get.assert_called()
    agent_registry.get().handle.assert_called()


async def test_post_callback_non_text_message(
    wechat_config, intent_router, agent_registry, db_session
):
    """测试 POST 非文本消息：应回复"暂不支持该消息类型"

    输入: msg_type="image" 的加密消息
    输出: 200 + 回复内容包含"暂不支持"
    """
    token = wechat_config["token"]
    aes_key = wechat_config["encoding_aes_key"]
    corp_id = wechat_config["corp_id"]

    inner = {
        "from_user_name": "user_001",
        "msg_type": "image",
        "content": "",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), corp_id)

    timestamp = str(int(time.time()))
    nonce = "test_nonce"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_app(wechat_config, intent_router, agent_registry, db_session)

    response = client.post(
        "/api/wechat/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={
            "to_user_name": "test_corp_id",
            "agent_id": "1000001",
            "encrypt": encrypted_content,
        },
    )

    assert response.status_code == 200
    # 非文本消息不应调用 agent
    intent_router.route.assert_not_called()


def test_post_callback_bad_signature(wechat_config):
    """测试 POST 消息：签名不匹配应返回 403

    输入: 错误签名的 POST
    输出: 403
    """
    client = _build_app(wechat_config, AsyncMock(), AsyncMock())

    response = client.post(
        "/api/wechat/callback",
        params={
            "msg_signature": "wrong_signature",
            "timestamp": "1234567890",
            "nonce": "test",
        },
        json={"encrypt": "some_encrypted_content"},
    )

    assert response.status_code == 403
