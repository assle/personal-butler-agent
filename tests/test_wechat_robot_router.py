"""
测试企业微信智能机器人 API 模式回调路由（URL 验证 + 消息接收）

Workflow:
1. GET /api/wechat/robot/callback: 验签 + 解密 echostr（receiveid=""）返回明文
2. POST /api/wechat/robot/callback: 解密 → 解析智能机器人 JSON → 群聊保存 + 触发总结
   或私聊意图路由 → 通过 response_url 主动推送回复 → 返回 200 success
3. 验证自建应用回调 /api/wechat/callback 不受影响（仍使用 CorpID 校验 + 被动加密回复）
"""
import base64
import hashlib
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch
from xml.etree import ElementTree

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.wechat.crypto import decrypt, encrypt
from src.wechat.robot_router import _is_summarize_trigger, create_robot_router
from src.models.group_message import GroupMessage


@pytest.fixture
def robot_intent_router():
    """创建 mock IntentRouter，默认返回 ("qa", 0.9)"""
    router = AsyncMock()
    router.route.return_value = ("qa", 0.9)
    return router


@pytest.fixture
def robot_agent_registry():
    """创建 mock AgentRegistry，默认返回回复 "这是机器人测试回复" 的 agent"""
    from src.schemas.response import AgentResponse

    agent = AsyncMock()
    agent.handle.return_value = AgentResponse(reply="这是机器人测试回复", data=None)

    registry = MagicMock()
    registry.get.return_value = agent
    return registry


@pytest.fixture
def robot_config():
    """生成测试用的智能机器人配置

    输出: dict，包含 token, encoding_aes_key
    注意: 智能机器人没有 corp_id，receiveid 为空字符串
    """
    return {
        "token": "robot_test_token",
        "encoding_aes_key": base64.b64encode(os.urandom(32)).decode(),
    }


@pytest.fixture
def mock_httpx_post():
    """Mock httpx.AsyncClient.post，捕获 response_url 推送调用"""
    with patch("src.wechat.robot_router.httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"errcode":0,"errmsg":"ok"}'
        mock_post.return_value = mock_response
        yield mock_post


def _build_robot_app(robot_config, intent_router, agent_registry, db_session=None):
    """构建带智能机器人路由的测试 FastAPI 应用

    参数:
        robot_config: 智能机器人配置 dict
        intent_router: mock IntentRouter
        agent_registry: mock AgentRegistry
        db_session: 可选，DB session 用于依赖覆盖

    返回:
        TestClient: FastAPI TestClient
    """
    app = FastAPI()
    router = create_robot_router(
        intent_router=intent_router,
        agent_registry=agent_registry,
        token=robot_config["token"],
        encoding_aes_key=robot_config["encoding_aes_key"],
    )
    app.include_router(router)

    if db_session is not None:
        from src.db.session import get_db
        app.dependency_overrides[get_db] = lambda: db_session

    return TestClient(app)


# ── GET URL 验证测试 ──


def test_robot_get_callback_url_verification_success(robot_config):
    """测试智能机器人 GET URL 验证：正确签名 + 解密 echostr（receiveid=""）返回明文

    输入: 正确签名的 msg_signature、加密的 echostr（receiveid=""）
    输出: 200 + 解密后的明文字符串
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    echostr_plain = "robot_echo_test_67890"
    echostr_encrypted = encrypt(aes_key, echostr_plain, "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce"

    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, echostr_encrypted])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, AsyncMock(), AsyncMock())

    response = client.get(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": echostr_encrypted,
        },
    )

    assert response.status_code == 200
    assert response.text == echostr_plain


def test_robot_get_callback_url_verification_bad_signature(robot_config):
    """测试智能机器人 GET URL 验证：错误签名应返回 403

    输入: 错误的 msg_signature
    输出: 403
    """
    client = _build_robot_app(robot_config, AsyncMock(), AsyncMock())

    response = client.get(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": "wrong_signature",
            "timestamp": "1234567890",
            "nonce": "test",
            "echostr": "whatever",
        },
    )

    assert response.status_code == 403


def test_robot_get_callback_receiveid_empty(robot_config):
    """测试智能机器人 echostr 解密：receiveid 必须为空字符串

    用 CorpID 加密的 echostr 在智能机器人回调中应解密失败（receiveid 不匹配）

    输入: 用 CorpID "test_corp" 加密的 echostr
    输出: 403（CorpIDMismatch）
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    echostr_encrypted = encrypt(aes_key, "some_echo", "test_corp")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, echostr_encrypted])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, AsyncMock(), AsyncMock())

    response = client.get(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": echostr_encrypted,
        },
    )

    assert response.status_code == 403


# ── POST 消息接收测试（智能机器人 JSON 格式 + response_url 回复）──


async def test_robot_post_callback_text_message(
    robot_config, robot_intent_router, robot_agent_registry, db_session, mock_httpx_post
):
    """测试智能机器人 POST 文本消息：正常路由到 agent 并通过 response_url 回复

    输入: 智能机器人 JSON 格式加密消息（私聊），含 response_url
    输出: 200 "success"；agent 流水线被调用；回复 POST 到 response_url
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    # 智能机器人 JSON 格式
    inner = {
        "msgid": "test_msg_001",
        "aibotid": "aibTestBot123",
        "chattype": "single",
        "from": {"userid": "robot_user_001"},
        "msgtype": "text",
        "text": {"content": "今天练什么"},
        "response_url": "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=test_response_001",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, robot_intent_router, robot_agent_registry, db_session)

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={
            "encrypt": encrypted_content,
        },
    )

    # 回调始终返回 200 success
    assert response.status_code == 200
    assert response.text.strip() == "success"

    # agent 流水线被调用
    robot_intent_router.route.assert_called()
    robot_agent_registry.get.assert_called()
    robot_agent_registry.get().handle.assert_called()

    # 回复通过 response_url 推送
    mock_httpx_post.assert_called_once()
    call_args = mock_httpx_post.call_args
    assert call_args[0][0] == "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=test_response_001"
    sent_payload = call_args[1]["json"]
    assert sent_payload["msgtype"] == "markdown"
    assert sent_payload["markdown"]["content"] == "这是机器人测试回复"


async def test_robot_post_callback_non_text_message(
    robot_config, robot_intent_router, robot_agent_registry, db_session, mock_httpx_post
):
    """测试智能机器人 POST 非文本消息：应回复"暂不支持该消息类型"

    输入: msgtype="image" 的智能机器人 JSON 格式加密消息
    输出: 200 "success"；agent 未被调用；response_url 收到"暂不支持"
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    inner = {
        "msgid": "test_msg_002",
        "aibotid": "aibTestBot123",
        "chattype": "single",
        "from": {"userid": "robot_user_img"},
        "msgtype": "image",
        "text": {"content": ""},
        "response_url": "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=test_resp_img",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, robot_intent_router, robot_agent_registry, db_session)

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={"encrypt": encrypted_content},
    )

    assert response.status_code == 200
    # 非文本消息不调用 agent
    robot_intent_router.route.assert_not_called()

    sent_payload = mock_httpx_post.call_args[1]["json"]
    assert sent_payload["markdown"]["content"] == "暂不支持该消息类型"


async def test_robot_post_callback_voice_message(
    robot_config, robot_intent_router, robot_agent_registry, db_session, mock_httpx_post
):
    """测试智能机器人 POST 语音消息：识别文本走正常意图路由

    输入: msgtype="voice" + voice.content="今天练胸" 的智能机器人 JSON 格式加密消息
    输出: 200 "success"；agent 流水线被调用；回复 POST 到 response_url
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    inner = {
        "msgid": "test_msg_voice_001",
        "aibotid": "aibTestBot123",
        "chattype": "single",
        "from": {"userid": "robot_voice_user_001"},
        "msgtype": "voice",
        "voice": {"content": "今天练胸"},
        "response_url": "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=test_resp_voice",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce_voice"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, robot_intent_router, robot_agent_registry, db_session)

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={"encrypt": encrypted_content},
    )

    assert response.status_code == 200
    assert response.text.strip() == "success"

    # agent 流水线应被调用（语音识别文本走正常路由）
    robot_intent_router.route.assert_called()
    robot_agent_registry.get.assert_called()
    robot_agent_registry.get().handle.assert_called()

    # 回复通过 response_url 推送
    mock_httpx_post.assert_called_once()
    sent_payload = mock_httpx_post.call_args[1]["json"]
    assert sent_payload["markdown"]["content"] == "这是机器人测试回复"


async def test_robot_post_callback_voice_message_empty(
    robot_config, robot_intent_router, robot_agent_registry, db_session, mock_httpx_post
):
    """测试智能机器人 POST 语音消息（识别为空）：静默不回复

    输入: msgtype="voice" + voice.content="" 的智能机器人 JSON 格式加密消息
    输出: 200 "success"；agent 未被调用；response_url 未被调用
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    inner = {
        "msgid": "test_msg_voice_002",
        "aibotid": "aibTestBot123",
        "chattype": "single",
        "from": {"userid": "robot_voice_user_002"},
        "msgtype": "voice",
        "voice": {"content": ""},
        "response_url": "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=test_resp_voice_empty",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce_voice_empty"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, robot_intent_router, robot_agent_registry, db_session)

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={"encrypt": encrypted_content},
    )

    assert response.status_code == 200
    assert response.text.strip() == "success"

    # agent 不应被调用
    robot_intent_router.route.assert_not_called()
    # response_url 不应被调用
    mock_httpx_post.assert_not_called()


def test_robot_post_callback_bad_signature(robot_config):
    """测试智能机器人 POST 消息：签名不匹配应返回 403

    输入: 错误签名的 POST
    输出: 403
    """
    client = _build_robot_app(robot_config, AsyncMock(), AsyncMock())

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": "wrong_signature",
            "timestamp": "1234567890",
            "nonce": "test",
        },
        json={"encrypt": "some_encrypted_content"},
    )

    assert response.status_code == 403


# ── 群聊消息处理测试 ──


async def test_robot_post_callback_group_message_trigger(
    robot_config, robot_intent_router, robot_agent_registry, db_session, mock_httpx_post
):
    """测试智能机器人群聊触发消息：保存到 DB 并通过 response_url 回复

    输入: chattype="group" 的智能机器人 JSON 格式，内容包含 "总结" 触发词
    输出: 200 "success"；消息已写入 DB；回复 POST 到 response_url
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    inner = {
        "msgid": "test_msg_group_001",
        "aibotid": "aibTestBot123",
        "chatid": "robot_group_123",
        "chattype": "group",
        "from": {"userid": "robot_group_user_001"},
        "msgtype": "text",
        "text": {"content": "@机器人 总结一下群消息"},
        "response_url": "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=test_resp_grp",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce_group"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, robot_intent_router, robot_agent_registry, db_session)

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={"encrypt": encrypted_content},
    )

    # 回调始终返回 200 success
    assert response.status_code == 200
    assert response.text.strip() == "success"

    # 回复通过 response_url 推送
    mock_httpx_post.assert_called_once()
    sent_payload = mock_httpx_post.call_args[1]["json"]
    assert sent_payload["markdown"]["content"] == "这是机器人测试回复"

    # 消息应已保存到数据库
    recent = await GroupMessage.get_recent(db_session, "robot_group_123", limit=10)
    assert len(recent) == 1
    assert recent[0].content == "@机器人 总结一下群消息"
    assert recent[0].user_id == "robot_group_user_001"


async def test_robot_post_callback_group_message_silent_collection(
    robot_config, robot_intent_router, robot_agent_registry, db_session, mock_httpx_post
):
    """测试智能机器人群聊非触发消息：保存到 DB 但静默返回不回复

    输入: chattype="group" 的智能机器人 JSON 格式，内容为普通聊天（无触发词）
    输出: 200 "success"；agent 未被调用；response_url 未被调用；消息已写入 DB
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    inner = {
        "msgid": "test_msg_group_002",
        "aibotid": "aibTestBot123",
        "chatid": "robot_group_456",
        "chattype": "group",
        "from": {"userid": "robot_group_user_002"},
        "msgtype": "text",
        "text": {"content": "明天什么时候开会"},
        "response_url": "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=test_resp_silent",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce_silent"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, robot_intent_router, robot_agent_registry, db_session)

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={"encrypt": encrypted_content},
    )

    assert response.status_code == 200
    assert response.text.strip() == "success"

    # agent 不应被调用
    robot_intent_router.route.assert_not_called()
    # response_url 不应被调用
    mock_httpx_post.assert_not_called()

    # 消息应已保存到数据库
    recent = await GroupMessage.get_recent(db_session, "robot_group_456", limit=10)
    assert len(recent) == 1
    assert recent[0].content == "明天什么时候开会"


async def test_robot_post_callback_private_chat_not_saved(
    robot_config, robot_intent_router, robot_agent_registry, db_session, mock_httpx_post
):
    """测试智能机器人私聊消息：不应保存到群聊消息表

    输入: chattype="single" 的智能机器人 JSON 格式
    输出: 200 "success"；回复 POST 到 response_url；group_messages 表中无数据
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    inner = {
        "msgid": "test_msg_private_001",
        "aibotid": "aibTestBot123",
        "chattype": "single",
        "from": {"userid": "robot_private_001"},
        "msgtype": "text",
        "text": {"content": "今天练什么"},
        "response_url": "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=test_resp_private",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce_private"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, robot_intent_router, robot_agent_registry, db_session)

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={"encrypt": encrypted_content},
    )

    assert response.status_code == 200
    assert response.text.strip() == "success"

    # agent 正常调用
    robot_intent_router.route.assert_called()
    # response_url 被调用
    mock_httpx_post.assert_called_once()

    # 私聊消息不应进入群聊消息表
    from sqlalchemy import select, func
    count_result = await db_session.execute(
        select(func.count()).select_from(GroupMessage)
    )
    assert count_result.scalar() == 0


async def test_robot_post_callback_no_response_url_graceful(
    robot_config, robot_intent_router, robot_agent_registry, db_session
):
    """测试智能机器人消息无 response_url 时优雅降级

    输入: 私聊消息但不含 response_url 字段
    输出: 200 "success"；不抛异常
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    inner = {
        "msgid": "test_msg_no_resp",
        "aibotid": "aibTestBot123",
        "chattype": "single",
        "from": {"userid": "user_no_resp"},
        "msgtype": "text",
        "text": {"content": "你好"},
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce_noresp"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, robot_intent_router, robot_agent_registry, db_session)

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={"encrypt": encrypted_content},
    )

    assert response.status_code == 200
    assert response.text.strip() == "success"


# ── 自建应用回调不受影响验证 ──

from src.wechat.router import create_wechat_router


def test_existing_wechat_callback_still_uses_corp_id():
    """验证自建应用回调仍使用 CorpID 校验（不受智能机器人影响）

    自建应用 GET URL 验证：用正确的 CorpID 加密 echostr 可以解密成功
    """
    corp_id = "existing_test_corp"
    token = "existing_token"
    aes_key = base64.b64encode(os.urandom(32)).decode()

    echostr_plain = "test_echo_corp_id"
    echostr_encrypted = encrypt(aes_key, echostr_plain, corp_id)

    timestamp = str(int(time.time()))
    nonce = "test_nonce_corp"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, echostr_encrypted])).encode()
    ).hexdigest()

    app = FastAPI()
    router = create_wechat_router(
        intent_router=AsyncMock(),
        agent_registry=MagicMock(),
        corp_id=corp_id,
        token=token,
        encoding_aes_key=aes_key,
    )
    app.include_router(router)
    client = TestClient(app)

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


def test_existing_wechat_callback_url_unchanged():
    """验证自建应用回调 URL 路径未变：仍然是 /api/wechat/callback

    确保新增智能机器人路由不会修改原有路由路径
    """
    corp_id = "test_corp_url"
    token = "test_token_url"
    aes_key = base64.b64encode(os.urandom(32)).decode()

    app = FastAPI()
    router = create_wechat_router(
        intent_router=AsyncMock(),
        agent_registry=MagicMock(),
        corp_id=corp_id,
        token=token,
        encoding_aes_key=aes_key,
    )
    app.include_router(router)
    client = TestClient(app)

    response = client.get(
        "/api/wechat/callback",
        params={
            "msg_signature": "any",
            "timestamp": "123",
            "nonce": "456",
            "echostr": "enc",
        },
    )

    assert response.status_code == 403


# ── _is_summarize_trigger 单元测试 ──


def test_robot_is_summarize_trigger_true():
    """测试触发词匹配：包含总结类关键词返回 True"""
    assert _is_summarize_trigger("@机器人 总结一下群消息") is True
    assert _is_summarize_trigger("帮我总结") is True
    assert _is_summarize_trigger("摘要一下今天的讨论") is True
    assert _is_summarize_trigger("概括一下") is True
    assert _is_summarize_trigger("汇总群聊") is True


def test_robot_is_summarize_trigger_false():
    """测试触发词不匹配：不含总结类关键词返回 False"""
    assert _is_summarize_trigger("明天什么时候开会") is False
    assert _is_summarize_trigger("大家好") is False
    assert _is_summarize_trigger("今天练什么") is False
    assert _is_summarize_trigger("") is False
