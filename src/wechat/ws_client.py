"""
企业微信智能机器人 WebSocket 长连接客户端
通过 WebSocket 连接企微服务器，实现消息接收、回复和主动推送

Workflow:
  1. connect() 建立 WebSocket 连接到 wss://openws.work.weixin.qq.com
  2. _subscribe() 发送 aibot_subscribe 认证
  3. _listen() 循环接收消息帧，分发给 on_message 回调
  4. send_reply() 通过 aibot_respond_msg 回复消息
  5. push_message() 通过 aibot_send_msg 主动推送消息
  6. _heartbeat() 每 30s 发送 ping 保活
  7. 断线后自动指数退避重连（1s → 2s → 4s → 最大 30s）
"""
import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable

import websockets
import websockets.exceptions

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)

# 收到消息的回调类型：参数为 (消息体 dict, 原始请求 req_id str)
OnMessageCallback = Callable[[dict, str], Awaitable[None]]


class WeComWSClient:
    """企业微信智能机器人 WebSocket 长连接客户端"""

    def __init__(self, bot_id: str, secret: str):
        """初始化长连接客户端

        参数:
            bot_id: 智能机器人 BotID（格式 aib-xxx）
            secret: 长连接专用 Secret
        """
        self._bot_id = bot_id
        self._secret = secret
        self._ws: websockets.ClientConnection | None = None
        self._running = False
        self._on_message: OnMessageCallback | None = None
        self._message_tasks: set[asyncio.Task] = set()

    @property
    def on_message(self) -> OnMessageCallback | None:
        """收到消息时的回调函数"""
        return self._on_message

    @on_message.setter
    def on_message(self, callback: OnMessageCallback):
        """设置收到消息时的回调函数

        参数:
            callback: async (msg: dict) -> None，msg 为解析后的消息 JSON
        """
        self._on_message = callback

    async def run(self):
        """启动长连接客户端，包含自动重连逻辑

        作为 asyncio Task 运行，持续维护 WebSocket 连接直到 stop() 被调用。
        """
        self._running = True
        retry_delay = 1
        while self._running:
            try:
                await self._connect_and_listen()
                retry_delay = 1  # 正常退出时重置延迟
            except (websockets.exceptions.ConnectionClosed,
                    websockets.exceptions.WebSocketException,
                    OSError) as e:
                if not self._running:
                    break
                logger.warning("WS disconnected: %s, reconnecting in %ds...", e, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)

    async def stop(self):
        """停止长连接客户端"""
        self._running = False
        tasks = list(self._message_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._ws is not None:
            await self._ws.close()

    async def _connect_and_listen(self):
        """建立连接、认证、启动心跳、循环接收消息"""
        async with websockets.connect(
            "wss://openws.work.weixin.qq.com",
            ping_interval=None,  # 自己管理心跳
        ) as ws:
            self._ws = ws
            await self._subscribe()
            logger.info("WS: subscribed successfully")
            heartbeat_task = asyncio.create_task(self._heartbeat())
            try:
                await self._listen()
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _subscribe(self):
        """发送 aibot_subscribe 认证请求"""
        req_id = str(uuid.uuid4())
        payload = {
            "cmd": "aibot_subscribe",
            "headers": {"req_id": req_id},
            "body": {
                "bot_id": self._bot_id,
                "secret": self._secret,
            },
        }
        await self._ws.send(json.dumps(payload, ensure_ascii=False))
        raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
        resp = json.loads(raw)
        if resp.get("errcode") != 0:
            raise RuntimeError(f"aibot_subscribe failed: {resp.get('errmsg', 'unknown')}")

    async def _listen(self):
        """循环接收消息帧，分发给 on_message 回调"""
        while self._running:
            raw = await self._ws.recv()
            data = json.loads(raw)
            cmd = data.get("cmd", "")
            if cmd == "aibot_msg_callback":
                msg = data.get("body", data)
                req_id = data.get("headers", {}).get("req_id", "")
                logger.info(
                    "WS: msg_callback msgid=%s chattype=%s chatid=%s from=%s msgtype=%s req_id=%s",
                    msg.get("msgid", ""),
                    msg.get("chattype", ""),
                    msg.get("chatid", ""),
                    msg.get("from", {}).get("userid", ""),
                    msg.get("msgtype", ""),
                    req_id,
                )
                if self._on_message is not None:
                    task = asyncio.create_task(self._on_message(msg, req_id))
                    self._message_tasks.add(task)
                    task.add_done_callback(self._handle_message_task_done)
            elif cmd == "aibot_event_callback":
                logger.info("WS: received event_callback: %s", data.get("body", {}).get("event_type", ""))
            else:
                logger.debug("WS: unknown cmd: %s", cmd)

    def _handle_message_task_done(self, task: asyncio.Task):
        """清理消息处理任务，并记录未捕获异常"""
        self._message_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("WS: message task failed: %s", e)

    async def _heartbeat(self):
        """每 30 秒发送 WebSocket ping 保活"""
        while self._running:
            await asyncio.sleep(30)
            if self._ws is not None:
                try:
                    await self._ws.ping()
                except websockets.exceptions.ConnectionClosed:
                    break

    async def send_reply(self, req_id: str, content: str) -> bool:
        """回复用户消息（通过 aibot_respond_msg）

        参数:
            req_id: 原始消息回调 headers 中的 req_id，用于关联回复
            content: 回复内容（支持 markdown）

        返回:
            bool: 发送成功返回 True
        """
        if self._ws is None:
            logger.warning("WS: send_reply called but not connected")
            return False
        try:
            payload = {
                "cmd": "aibot_respond_msg",
                "headers": {"req_id": req_id},
                "body": {
                    "msgtype": "markdown",
                    "markdown": {"content": content},
                },
            }
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
            return True
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WS: send_reply failed, connection closed")
            return False

    async def push_message(
        self,
        target_type: str,
        target_id: str,
        msgtype: str = "markdown",
        content: str = "",
    ) -> bool:
        """主动推送消息（通过 aibot_send_msg）

        参数:
            target_type: "single" 或 "group"
            target_id: userid（单聊）或 chatid（群聊）
            msgtype: 消息类型，默认 "markdown"
            content: 消息内容

        返回:
            bool: 发送成功返回 True
        """
        if self._ws is None:
            logger.warning("WS: push_message called but not connected")
            return False
        try:
            body = {
                "msgtype": msgtype,
                msgtype: {"content": content},
            }
            if target_type == "group":
                body["chatid"] = target_id
            else:
                body["userid"] = target_id
            payload = {
                "cmd": "aibot_send_msg",
                "headers": {"req_id": str(uuid.uuid4())},
                "body": body,
            }
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
            logger.info(
                "WS: pushed message to %s=%s, type=%s",
                target_type, target_id, msgtype,
            )
            return True
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WS: push_message failed, connection closed")
            return False
