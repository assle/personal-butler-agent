"""
WebSocket 客户端测试
测试 WeComWSClient 的连接、认证、消息收发逻辑
使用 mock websocket 避免真实网络调用
"""
import json
import uuid
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def ws_client():
    """创建 WeComWSClient 实例用于测试"""
    from src.wechat.ws_client import WeComWSClient
    return WeComWSClient(bot_id="aib-test123", secret="test-secret")


@pytest.mark.asyncio
async def test_ws_client_creation(ws_client):
    """验证客户端创建后属性正确"""
    assert ws_client._bot_id == "aib-test123"
    assert ws_client._secret == "test-secret"
    assert ws_client.on_message is None
    assert ws_client._running is False


@pytest.mark.asyncio
async def test_on_message_setter(ws_client):
    """验证 on_message 回调设置"""
    async def dummy_cb(msg):
        pass
    ws_client.on_message = dummy_cb
    assert ws_client.on_message is dummy_cb


@pytest.mark.asyncio
async def test_send_reply_when_not_connected(ws_client):
    """验证未连接时 send_reply 返回 False"""
    ok = await ws_client.send_reply("req-1", "hello")
    assert ok is False


@pytest.mark.asyncio
async def test_push_message_when_not_connected(ws_client):
    """验证未连接时 push_message 返回 False"""
    ok = await ws_client.push_message("single", "user1", "markdown", "hello")
    assert ok is False


@pytest.mark.asyncio
async def test_stop_when_not_connected(ws_client):
    """验证 stop 在不连接时也不报错"""
    ws_client._running = True
    await ws_client.stop()


class FakeWebSocket:
    """模拟 websocket 连接，记录发出的消息并可控地返回接收消息"""
    def __init__(self, responses=None):
        self.sent = []
        self._responses = responses or []
        self._recv_idx = 0

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        if self._recv_idx < len(self._responses):
            resp = self._responses[self._recv_idx]
            self._recv_idx += 1
            return resp
        raise Exception("no more mock responses")

    async def ping(self):
        pass

    async def close(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
async def test_subscribe_sends_correct_payload(ws_client):
    """验证 _subscribe 发送正确的认证消息"""
    sub_resp = json.dumps({"headers": {"req_id": "x"}, "errcode": 0, "errmsg": "ok"})
    fake_ws = FakeWebSocket(responses=[sub_resp])

    ws_client._ws = fake_ws
    await ws_client._subscribe()

    assert len(fake_ws.sent) == 1
    sent = fake_ws.sent[0]
    assert sent["cmd"] == "aibot_subscribe"
    assert sent["body"]["bot_id"] == "aib-test123"
    assert sent["body"]["secret"] == "test-secret"


@pytest.mark.asyncio
async def test_subscribe_failure_raises(ws_client):
    """验证认证失败时抛出 RuntimeError"""
    sub_resp = json.dumps({"headers": {"req_id": "x"}, "errcode": 40001, "errmsg": "invalid secret"})
    fake_ws = FakeWebSocket(responses=[sub_resp])

    ws_client._ws = fake_ws
    with pytest.raises(RuntimeError, match="aibot_subscribe failed"):
        await ws_client._subscribe()


@pytest.mark.asyncio
async def test_listen_dispatches_messages_without_blocking_receive(ws_client):
    """验证消息处理未完成时，_listen 仍能继续接收后续消息"""
    first = json.dumps({
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-1"},
        "body": {
            "msgid": "msg-1",
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    })
    second = json.dumps({
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-2"},
        "body": {
            "msgid": "msg-2",
            "msgtype": "text",
            "text": {"content": "world"},
        },
    })
    fake_ws = FakeWebSocket(responses=[first, second])
    ws_client._ws = fake_ws
    ws_client._running = True
    started = []
    first_can_finish = asyncio.Event()

    async def slow_callback(msg, req_id):
        started.append(req_id)
        if req_id == "req-1":
            await first_can_finish.wait()

    ws_client.on_message = slow_callback

    listen_task = asyncio.create_task(ws_client._listen())
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert started == ["req-1", "req-2"]

    ws_client._running = False
    first_can_finish.set()
    await asyncio.gather(listen_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_send_reply_sends_correct_payload(ws_client):
    """验证 send_reply 发送正确的回复消息格式"""
    fake_ws = FakeWebSocket()
    ws_client._ws = fake_ws

    ok = await ws_client.send_reply("original-req-id", "hello world")
    assert ok is True
    assert len(fake_ws.sent) == 1
    sent = fake_ws.sent[0]
    assert sent["cmd"] == "aibot_respond_msg"
    assert sent["headers"]["req_id"] == "original-req-id"
    assert sent["body"]["msgtype"] == "markdown"
    assert sent["body"]["markdown"]["content"] == "hello world"
    assert "msgid" not in sent["body"]


@pytest.mark.asyncio
async def test_push_message_to_user(ws_client):
    """验证 push_message 向用户推送的格式"""
    fake_ws = FakeWebSocket()
    ws_client._ws = fake_ws

    ok = await ws_client.push_message("single", "user1", "markdown", "test push")
    assert ok is True
    sent = fake_ws.sent[0]
    assert sent["cmd"] == "aibot_send_msg"
    assert sent["body"]["userid"] == "user1"
    assert "chatid" not in sent["body"]


@pytest.mark.asyncio
async def test_push_message_to_group(ws_client):
    """验证 push_message 向群聊推送的格式"""
    fake_ws = FakeWebSocket()
    ws_client._ws = fake_ws

    ok = await ws_client.push_message("group", "chat-99", "markdown", "group push")
    assert ok is True
    sent = fake_ws.sent[0]
    assert sent["cmd"] == "aibot_send_msg"
    assert sent["body"]["chatid"] == "chat-99"
    assert "userid" not in sent["body"]
