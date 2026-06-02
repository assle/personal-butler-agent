# 企业微信智能机器人长连接模式 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将智能机器人从 HTTP 回调模式切换到 WebSocket 长连接模式，并实现 APScheduler 定时 LLM 推送

**Architecture:** 新增 `WeComWSClient` 维护一条 WebSocket 长连接替代 HTTP 回调接收消息，新增 `SchedulerManager` 管理定时任务触发 agent 管线后通过 WS 推送。Agent 管线零改动。

**Tech Stack:** Python 3.13+, `websockets` 库, `apscheduler>=3.10.0` (已有), FastAPI lifespan

---

### Task 1: 添加 websockets 依赖并更新配置

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/config.py`
- Check: `.env.example`

- [ ] **Step 1: 添加 websockets 依赖**

```bash
uv add websockets
```

- [ ] **Step 2: 更新 `src/config.py` — 新增长连接和调度器字段，移除旧字段**

将整个文件替换为：

```python
"""
应用配置管理
从 .env 文件加载所有运行时配置，包括 LLM、数据库和企业微信相关参数

Workflow:
1. Settings 类通过 pydantic-settings 自动从 .env 文件加载环境变量
2. 未配置的字段使用空字符串默认值，避免应用启动失败
3. 全局 settings 实例在模块加载时创建，供所有模块导入使用
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置类，所有字段从 .env 文件自动加载"""
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # DeepSeek LLM 配置
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # SQLite 数据库配置
    database_url: str = "sqlite+aiosqlite:///butler.db"

    # 企业微信自建应用配置（回调消息加解密）
    wechat_corp_id: str = ""
    wechat_token: str = ""
    wechat_encoding_aes_key: str = ""
    wechat_agent_id: str = ""

    # 企业微信智能机器人长连接模式配置
    wecom_aibot_bot_id: str = ""
    wecom_aibot_secret: str = ""

    # 定时推送配置
    scheduler_cron: str = "0 9 * * *"
    scheduler_target_type: str = "single"
    scheduler_target_id: str = ""
    scheduler_message: str = "今日训练建议"
    scheduler_intent: str = "today_plan"


settings = Settings()
```

- [ ] **Step 3: 更新 `.env.example`**

```bash
# 检查 .env.example 文件内容，确保包含新字段
grep -c "WECOM_AIBOT" .env.example || echo "需要添加新字段"
```

Read `.env.example` 后添加新字段说明（如文件存在）。

- [ ] **Step 4: 运行现有测试确认配置变更不破坏测试**

```bash
uv run pytest tests/test_config.py -v
```

期望: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/config.py .env.example
git commit -m "feat: add websockets dep and long-connection + scheduler config fields"
```

---

### Task 2: 实现 WebSocket 长连接客户端

**Files:**
- Create: `src/wechat/ws_client.py`

- [ ] **Step 1: 创建 `src/wechat/ws_client.py`**

```python
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

# 收到消息的回调类型
OnMessageCallback = Callable[[dict], Awaitable[None]]


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
                logger.info("WS: received msg_callback, msgid=%s", msg.get("msgid", ""))
                if self._on_message is not None:
                    await self._on_message(msg)
            elif cmd == "aibot_event_callback":
                logger.info("WS: received event_callback: %s", data.get("body", {}).get("event_type", ""))
            else:
                logger.debug("WS: unknown cmd: %s", cmd)

    async def _heartbeat(self):
        """每 30 秒发送 WebSocket ping 保活"""
        while self._running:
            await asyncio.sleep(30)
            if self._ws is not None:
                try:
                    await self._ws.ping()
                except websockets.exceptions.ConnectionClosed:
                    break

    async def send_reply(self, msgid: str, content: str) -> bool:
        """回复用户消息（通过 aibot_respond_msg）

        参数:
            msgid: 原始消息的 msgid
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
                "headers": {"req_id": str(uuid.uuid4())},
                "body": {
                    "msgid": msgid,
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
```

- [ ] **Step 2: 验证文件语法**

```bash
uv run python3 -c "from src.wechat.ws_client import WeComWSClient; print('OK')"
```

期望: 输出 OK

- [ ] **Step 3: Commit**

```bash
git add src/wechat/ws_client.py
git commit -m "feat: add WeComWSClient for long-connection mode"
```

---

### Task 3: 实现消息处理回调

**Files:**
- Create: `src/wechat/message_handler.py`

- [ ] **Step 1: 创建 `src/wechat/message_handler.py`**

```python
"""
企业微信长连接消息处理回调
从 WebSocket 收到消息后，调用 intent_router + agent_registry 处理并回复

Workflow:
  ws 收到 aibot_msg_callback → handle_ws_message() 
    → 解析消息字段
    → 群聊消息保存到 DB + 触发词检测
    → 私聊消息 intent 路由 → agent 处理
    → ws_client.send_reply() 回复
"""
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.registry import AgentRegistry
from src.intent.router import IntentRouter

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)

_SUMMARIZE_KEYWORDS = ["总结", "摘要", "概括", "汇总"]


async def handle_ws_message(
    msg: dict,
    ws_client,
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    db: AsyncSession,
):
    """处理从 WebSocket 收到的消息回调

    参数:
        msg: aibot_msg_callback 的 body 部分，包含 from.userid, text.content, chatid 等
        ws_client: WeComWSClient 实例，用于回复消息
        intent_router: 意图路由器
        agent_registry: agent 注册表
        db: 数据库异步会话
    """
    from_user = msg.get("from", {}).get("userid", "")
    msg_type = msg.get("msgtype", "text")
    msgid = msg.get("msgid", "")

    # 提取文本内容
    if msg_type == "voice":
        content = msg.get("voice", {}).get("content", "")
        if not content:
            logger.info("WS: voice recognition empty, ignoring")
            return
    else:
        content = msg.get("text", {}).get("content", "")

    chat_id = msg.get("chatid", "")
    chat_type = msg.get("chattype", "single")

    logger.info(
        "WS handler: msg_type=%s, from_user=%s, chat_type=%s, chat_id=%s, content=%s",
        msg_type, from_user, chat_type, chat_id, content[:200],
    )

    # 群聊消息处理
    is_group_trigger = False
    if chat_type == "group" and chat_id:
        from src.models.group_message import GroupMessage
        await GroupMessage.save(db, chat_id, from_user, content, int(time.time()))
        await GroupMessage.cleanup(db, chat_id, keep=200)

        if _is_summarize_trigger(content):
            is_group_trigger = True
        else:
            logger.info("WS handler: non-trigger group message, no reply")
            return

    # 非文本且非语音消息
    if msg_type not in ("text", "voice"):
        reply_text = "暂不支持该消息类型"
    elif is_group_trigger:
        agent = agent_registry.get("summarize_group")
        if agent is None:
            reply_text = "抱歉，无法处理该消息"
        else:
            try:
                result = await agent.handle(
                    "summarize_group", content, from_user, db,
                    extra_state={"chat_id": chat_id, "chat_type": "group"},
                )
                reply_text = result.reply
            except Exception as e:
                logger.exception("WS handler: agent error: %s", e)
                reply_text = "抱歉，处理消息时遇到错误"
    else:
        # 私聊消息：意图路由 + agent 处理
        try:
            intent, _confidence = await intent_router.route(content)
            logger.info("WS handler: intent=%s", intent)
            agent = agent_registry.get(intent)
            if agent is None:
                reply_text = "抱歉，无法处理该消息"
            else:
                try:
                    result = await agent.handle(
                        intent, content, from_user, db,
                        extra_state={"chat_type": chat_type, "chat_id": chat_id or None},
                    )
                    reply_text = result.reply
                except Exception as e:
                    logger.exception("WS handler: agent error: %s", e)
                    reply_text = "LLM 服务暂时不可用，请稍后重试。"
        except Exception as e:
            logger.exception("WS handler: unexpected error: %s", e)
            reply_text = "抱歉，处理消息时遇到错误"

    logger.info("WS handler: reply_text=%s", reply_text[:200])
    await ws_client.send_reply(msgid, reply_text)


def _is_summarize_trigger(content: str) -> bool:
    """检测消息是否触发群聊总结"""
    return any(kw in content for kw in _SUMMARIZE_KEYWORDS)
```

- [ ] **Step 2: 验证文件语法**

```bash
uv run python3 -c "from src.wechat.message_handler import handle_ws_message; print('OK')"
```

期望: 输出 OK

- [ ] **Step 3: Commit**

```bash
git add src/wechat/message_handler.py
git commit -m "feat: add WS message handler callback"
```

---

### Task 4: 实现 APScheduler 调度管理器

**Files:**
- Create: `src/scheduler/__init__.py`

- [ ] **Step 1: 创建 `src/scheduler/__init__.py`**

```python
"""
APScheduler 定时调度管理器
管理定时任务的启动、停止和 job 注册

Workflow:
  1. SchedulerManager.start() 启动 AsyncIOScheduler
  2. 注册 scheduled_push job，到点触发 agent 管线
  3. agent 处理后通过 ws_client.push_message() 推送到目标
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)


class SchedulerManager:
    """定时调度管理器，封装 APScheduler 的生命周期"""

    def __init__(
        self,
        ws_client,
        agent_registry,
        cron_expression: str,
        target_type: str,
        target_id: str,
        message: str,
        intent: str,
        db_session_factory,
    ):
        """初始化调度管理器

        参数:
            ws_client: WeComWSClient 实例，用于推送消息
            agent_registry: AgentRegistry 实例
            cron_expression: cron 表达式（如 "0 9 * * *"）
            target_type: 推送目标类型 "single" / "group"
            target_id: 推送目标 userid 或 chatid
            message: 发给 agent 的触发消息
            intent: agent intent 标识
            db_session_factory: 异步数据库会话工厂
        """
        self._ws = ws_client
        self._agent_registry = agent_registry
        self._cron = cron_expression
        self._target_type = target_type
        self._target_id = target_id
        self._message = message
        self._intent = intent
        self._db_session_factory = db_session_factory
        self._scheduler = AsyncIOScheduler()

    def start(self):
        """启动调度器，注册定时任务"""
        self._scheduler.add_job(
            self._scheduled_push,
            trigger=CronTrigger.from_crontab(self._cron),
            id="scheduled_push",
            name="定时推送",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "Scheduler: started, cron=%s, target=%s=%s, intent=%s, msg=%s",
            self._cron, self._target_type, self._target_id,
            self._intent, self._message,
        )

    def shutdown(self):
        """关闭调度器"""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler: shutdown")

    async def _scheduled_push(self):
        """定时推送 job：触发 agent 管线 → WS 主动推送"""
        if self._ws is None:
            logger.error("Scheduler: ws_client is None, cannot push")
            return
        agent = self._agent_registry.get(self._intent)
        if agent is None:
            logger.error("Scheduler: agent not found for intent=%s", self._intent)
            return
        async with self._db_session_factory() as db:
            try:
                result = await agent.handle(
                    intent=self._intent,
                    message=self._message,
                    user_id=self._target_id,
                    db=db,
                    extra_state={"chat_type": self._target_type},
                )
                await self._ws.push_message(
                    target_type=self._target_type,
                    target_id=self._target_id,
                    msgtype="markdown",
                    content=result.reply,
                )
                logger.info(
                    "Scheduler: pushed to %s=%s, reply=%s",
                    self._target_type, self._target_id, result.reply[:100],
                )
                await db.commit()
            except Exception as e:
                logger.exception("Scheduler: push failed: %s", e)
                await db.rollback()
```

- [ ] **Step 2: 验证文件语法**

```bash
uv run python3 -c "from src.scheduler import SchedulerManager; print('OK')"
```

期望: 输出 OK

- [ ] **Step 3: Commit**

```bash
git add src/scheduler/__init__.py
git commit -m "feat: add APScheduler manager for scheduled LLM push"
```

---

### Task 5: 更新 main.py lifespan 集成

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: 替换 `src/main.py`**

```python
"""
Personal Butler Agent 应用入口
负责 FastAPI 应用初始化、单例组件创建和路由注册

Workflow:
1. 创建 LLMClient、IntentRouter、各业务 agent 单例
2. 向 AgentRegistry 注册所有 intent → agent 映射
3. lifespan 中初始化数据库表结构
4. 条件启动 WebSocket 长连接客户端（仅当 WECOM_AIBOT_BOT_ID 已配置）
5. 条件启动 APScheduler 定时调度器（仅当 SCHEDULER_CRON 和 SCHEDULER_TARGET_ID 已配置）
6. 注册调试路由（始终可用）
7. 条件注册企业微信自建应用回调路由（仅当 WECHAT_CORP_ID 和 WECHAT_TOKEN 已配置）
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import settings
from src.llm.client import LLMClient
from src.intent.router import IntentRouter
from src.agents.fitness import FitnessAgent
from src.agents.summary import SummaryAgent
from src.agents.meal import MealAgent
from src.agents.qa import QAAgent
from src.agents.registry import AgentRegistry
from src.router.debug import create_debug_router

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)

llm_client = LLMClient()
intent_router = IntentRouter(llm_client=llm_client)
fitness_agent = FitnessAgent(llm_client=llm_client)
summary_agent = SummaryAgent(llm_client=llm_client)
meal_agent = MealAgent(llm_client=llm_client)
qa_agent = QAAgent(llm_client=llm_client)

agent_registry = AgentRegistry()
agent_registry.register("log_training", fitness_agent)
agent_registry.register("today_plan", fitness_agent)
agent_registry.register("summarize_text", summary_agent)
agent_registry.register("summarize_group", summary_agent)
agent_registry.register("make_meal_plan", meal_agent)
agent_registry.register("qa", qa_agent)
agent_registry.register("unknown", qa_agent)
agent_registry.set_fallback(qa_agent)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理

    应用启动时自动创建数据库表结构，启动 WebSocket 长连接和定时调度器。
    关闭时释放连接。

    参数:
        app: FastAPI 应用实例
    """
    from src.db.base import Base
    from src.db.session import engine, async_session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    ws_task = None
    scheduler = None

    # 启动智能机器人 WebSocket 长连接
    if settings.wecom_aibot_bot_id:
        from src.wechat.ws_client import WeComWSClient
        from src.wechat.message_handler import handle_ws_message

        ws_client = WeComWSClient(
            bot_id=settings.wecom_aibot_bot_id,
            secret=settings.wecom_aibot_secret,
        )
        app.state.ws_client = ws_client

        async def on_message_callback(msg: dict):
            async with async_session() as db:
                try:
                    await handle_ws_message(
                        msg, ws_client, intent_router, agent_registry, db,
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.exception("WS message handler: unhandled error")

        ws_client.on_message = on_message_callback
        ws_task = asyncio.create_task(ws_client.run())
        logger.info("WS client: started")

    # 启动 APScheduler 定时推送（需要 WS 客户端先启动）
    if settings.scheduler_cron and settings.scheduler_target_id and settings.wecom_aibot_bot_id:
        from src.scheduler import SchedulerManager

        scheduler = SchedulerManager(
            ws_client=app.state.ws_client if settings.wecom_aibot_bot_id else None,
            agent_registry=agent_registry,
            cron_expression=settings.scheduler_cron,
            target_type=settings.scheduler_target_type,
            target_id=settings.scheduler_target_id,
            message=settings.scheduler_message,
            intent=settings.scheduler_intent,
            db_session_factory=async_session,
        )
        scheduler.start()
        app.state.scheduler = scheduler

    yield

    # 关闭
    if scheduler is not None:
        scheduler.shutdown()
    if ws_task is not None:
        app.state.ws_client.stop() if hasattr(app.state, "ws_client") else None
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
    await engine.dispose()


app = FastAPI(title="Personal Butler Agent", version="0.1.0", lifespan=lifespan)

# 调试路由（始终注册，用于本地开发测试）
debug_router = create_debug_router(
    intent_router=intent_router,
    agent_registry=agent_registry,
)
app.include_router(debug_router)

# 企业微信自建应用回调路由（仅当配置了 CorpID 和 Token 时注册）
if settings.wechat_corp_id and settings.wechat_token:
    from src.wechat.router import create_wechat_router

    wechat_router = create_wechat_router(
        intent_router=intent_router,
        agent_registry=agent_registry,
        corp_id=settings.wechat_corp_id,
        token=settings.wechat_token,
        encoding_aes_key=settings.wechat_encoding_aes_key,
    )
    app.include_router(wechat_router)
```

- [ ] **Step 2: 验证应用启动（不带长连接配置）**

```bash
timeout 3 uv run uvicorn src.main:app 2>&1 || true
```

期望: 正常启动，没有 import 错误

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: integrate WS client and scheduler into lifespan"
```

---

### Task 6: 清理旧代码

**Files:**
- Delete: `src/wechat/robot_router.py`
- Delete: `src/wechat/webhook.py`
- Modify: `src/wechat/__init__.py`
- Delete: `tests/test_wechat_robot_router.py`
- Delete: `tests/test_wechat_webhook.py`

- [ ] **Step 1: 删除旧文件**

```bash
rm src/wechat/robot_router.py
rm src/wechat/webhook.py
rm tests/test_wechat_robot_router.py
rm tests/test_wechat_webhook.py
```

- [ ] **Step 2: 更新 `src/wechat/__init__.py`**

替换为：

```python
"""
企业微信集成模块
提供消息加解密、签名验证、WebSocket 长连接客户端和回调路由功能

Workflow:
1. crypto.py: AES-256-CBC 加解密 + SHA1 签名验证（纯函数，无外部依赖）
2. messages.py: XML 消息解析（EncryptedMessage → InnerMessage）和构建
3. ws_client.py: WebSocket 长连接客户端（智能机器人消息收发和主动推送）
4. message_handler.py: 长连接消息处理回调（意图路由 → agent → 回复）
5. router.py: 自建应用 FastAPI 路由工厂（GET 回调验证 + POST 消息接收 → 意图路由 → agent → 加密回复）
"""
from .crypto import (
    CorpIDMismatch,
    DecryptError,
    SignatureError,
    decrypt,
    encrypt,
    verify_signature,
)
from .messages import (
    EncryptedMessage,
    InnerMessage,
    build_encrypted_reply_xml,
    build_reply_xml,
    parse_encrypted_xml,
    parse_inner_xml,
)
from .router import create_wechat_router
from .ws_client import WeComWSClient
from .message_handler import handle_ws_message

__all__ = [
    # crypto
    "verify_signature",
    "encrypt",
    "decrypt",
    "SignatureError",
    "DecryptError",
    "CorpIDMismatch",
    # messages
    "EncryptedMessage",
    "InnerMessage",
    "parse_encrypted_xml",
    "parse_inner_xml",
    "build_reply_xml",
    "build_encrypted_reply_xml",
    # ws_client
    "WeComWSClient",
    # message_handler
    "handle_ws_message",
    # router
    "create_wechat_router",
]
```

- [ ] **Step 3: 运行测试确认无 import 错误**

```bash
uv run pytest -v 2>&1 | tail -5
```

期望: 所有剩余测试通过（robot_router 和 webhook 测试已删除，不影响其他测试）

- [ ] **Step 4: Commit**

```bash
git add -u src/wechat/ tests/
git commit -m "refactor: remove callback-mode robot_router and webhook, replaced by ws_client"
```

---

### Task 7: 编写 WebSocket 客户端测试

**Files:**
- Create: `tests/test_ws_client.py`

- [ ] **Step 1: 创建 `tests/test_ws_client.py`**

```python
"""
WebSocket 客户端测试
测试 WeComWSClient 的连接、认证、消息收发逻辑
使用 mock websocket 避免真实网络调用
"""
import json
import uuid
import pytest
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
    ok = await ws_client.send_reply("msgid-1", "hello")
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
async def test_send_reply_sends_correct_payload(ws_client):
    """验证 send_reply 发送正确的回复消息格式"""
    fake_ws = FakeWebSocket()
    ws_client._ws = fake_ws

    ok = await ws_client.send_reply("msg-42", "hello world")
    assert ok is True
    assert len(fake_ws.sent) == 1
    sent = fake_ws.sent[0]
    assert sent["cmd"] == "aibot_respond_msg"
    assert sent["body"]["msgid"] == "msg-42"
    assert sent["body"]["msgtype"] == "markdown"
    assert sent["body"]["markdown"]["content"] == "hello world"


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
```

- [ ] **Step 2: 运行 WS 测试**

```bash
uv run pytest tests/test_ws_client.py -v
```

期望: 9 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_ws_client.py
git commit -m "test: add WeComWSClient unit tests"
```

---

### Task 8: 编写调度器测试

**Files:**
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: 创建 `tests/test_scheduler.py`**

```python
"""
调度器测试
测试 SchedulerManager 的创建、job 触发和推送逻辑
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_ws():
    """创建 mock WebSocket 客户端"""
    ws = AsyncMock()
    ws.push_message.return_value = True
    return ws


@pytest.fixture
def mock_registry():
    """创建 mock AgentRegistry"""
    from src.agents.registry import AgentRegistry
    registry = AgentRegistry()
    return registry


@pytest.fixture
def mock_db_factory():
    """创建 mock 数据库会话工厂"""
    from unittest.mock import AsyncMock, MagicMock
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock()
    factory.return_value = session
    return factory


@pytest.mark.asyncio
async def test_scheduler_creation(mock_ws, mock_registry, mock_db_factory):
    """验证 SchedulerManager 创建不报错"""
    from src.scheduler import SchedulerManager

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="今日训练建议",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )
    assert mgr._cron == "0 9 * * *"
    assert mgr._target_type == "single"
    assert mgr._target_id == "user1"


@pytest.mark.asyncio
async def test_scheduled_push_calls_agent_and_pushes(mock_ws, mock_registry, mock_db_factory):
    """验证 _scheduled_push 调用 agent 并推送结果"""
    from src.scheduler import SchedulerManager
    from src.schemas.response import AgentResponse
    from unittest.mock import AsyncMock

    # 注册一个 mock agent
    mock_agent = AsyncMock()
    mock_agent.handle.return_value = AgentResponse(
        reply="今日训练计划：练肩 + 哑铃推举",
        data=None,
    )
    mock_registry.register("today_plan", mock_agent)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="今日训练建议",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )

    await mgr._scheduled_push()

    # 验证 agent.handle 被调用
    mock_agent.handle.assert_called_once()
    call_kwargs = mock_agent.handle.call_args
    assert call_kwargs.kw["intent"] == "today_plan"
    assert call_kwargs.kw["message"] == "今日训练建议"
    assert call_kwargs.kw["user_id"] == "user1"

    # 验证 ws.push_message 被调用
    mock_ws.push_message.assert_called_once_with(
        target_type="single",
        target_id="user1",
        msgtype="markdown",
        content="今日训练计划：练肩 + 哑铃推举",
    )


@pytest.mark.asyncio
async def test_scheduled_push_handles_agent_not_found(mock_ws, mock_registry, mock_db_factory):
    """验证 agent 未注册时不崩溃"""
    from src.scheduler import SchedulerManager

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="test",
        intent="nonexistent",
        db_session_factory=mock_db_factory,
    )

    await mgr._scheduled_push()
    # 不应抛出异常，且不应调用 push_message
    mock_ws.push_message.assert_not_called()


@pytest.mark.asyncio
async def test_scheduled_push_handles_agent_error(mock_ws, mock_registry, mock_db_factory):
    """验证 agent 处理异常时不崩溃"""
    from src.scheduler import SchedulerManager
    from unittest.mock import AsyncMock

    mock_agent = AsyncMock()
    mock_agent.handle.side_effect = Exception("LLM error")
    mock_registry.register("today_plan", mock_agent)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="test",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )

    await mgr._scheduled_push()
    # 不应抛出异常，但 push_message 不应被调用
    mock_ws.push_message.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_start_and_shutdown(mock_ws, mock_registry, mock_db_factory):
    """验证调度器启动和关闭不报错"""
    from src.scheduler import SchedulerManager

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="test",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )
    mgr.start()
    mgr.shutdown()
```

- [ ] **Step 2: 运行调度器测试**

```bash
uv run pytest tests/test_scheduler.py -v
```

期望: 5 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_scheduler.py
git commit -m "test: add SchedulerManager unit tests"
```

---

### Task 9: 编写消息处理器测试

**Files:**
- Create: `tests/test_message_handler.py`

- [ ] **Step 1: 创建 `tests/test_message_handler.py`**

```python
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

    await handle_ws_message(msg, mock_ws, mock_intent_router, mock_agent_registry, db_session)

    mock_intent_router.route.assert_called_once_with("今天练什么")
    mock_ws.send_reply.assert_called_once_with("msg-1", "mock reply")


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

    await handle_ws_message(msg, mock_ws, mock_intent_router, mock_agent_registry, db_session)

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

    await handle_ws_message(msg, mock_ws, mock_intent_router, mock_agent_registry, db_session)

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

    await handle_ws_message(msg, mock_ws, mock_intent_router, mock_agent_registry, db_session)

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

    await handle_ws_message(msg, mock_ws, mock_intent_router, mock_agent_registry, db_session)

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

    await handle_ws_message(msg, mock_ws, mock_intent_router, mock_agent_registry, db_session)

    mock_ws.send_reply.assert_called_once()
    args = mock_ws.send_reply.call_args
    assert "暂不支持" in args.args[1]
```

- [ ] **Step 2: 运行消息处理器测试**

```bash
uv run pytest tests/test_message_handler.py -v
```

期望: 6 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_message_handler.py
git commit -m "test: add message handler unit tests"
```

---

### Task 10: 全文回归 + 文档更新

- [ ] **Step 1: 运行全部测试**

```bash
uv run pytest -v 2>&1
```

期望: 全部通过（删除 robot_router 和 webhook 测试后约 ~100 tests）

- [ ] **Step 2: 更新 `docs/agent/config-variables.md`**

在文档中添加新的配置项表格，移除旧的 `WECHAT_ROBOT_TOKEN`、`WECHAT_ROBOT_ENCODING_AES_KEY`、`WECHAT_WEBHOOK_URL` 三个字段说明。

- [ ] **Step 3: 更新 `docs/agent/decisions.md`**

添加 ADR-011:

```markdown
## ADR-011: 智能机器人长连接模式替代回调模式

智能机器人从 HTTP 回调模式切换到 WebSocket 长连接模式。

Reasoning:
- **主动推送**: 长连接模式支持 `aibot_send_msg` 主动推送，回调模式仅能通过 `response_url` 被动回复。APScheduler 定时推送依赖此能力。
- **简化部署**: 长连接模式无需公网 IP/域名/SSL、无需消息加解密，降低部署门槛。
- **消除 5 秒超时**: WebSocket 长连接无 HTTP 响应超时限制，LLM 处理时长不受限制。
- **统一通道**: 消息接收、回复、主动推送全部走一条 WebSocket，消除群机器人 webhook 的冗余依赖。
- **官方演进方向**: 2026 年 3 月企业微信发布长连接模式，这是官方重点迭代方向。

Trade-off: 需要维护 WebSocket 连接（心跳、断线重连），增加了一定的运维复杂度。但这被更简单的部署和统一的消息通道所抵消。
```

- [ ] **Step 4: 更新 `docs/agent/upgrade-roadmap.md`**

将 "2.1 APScheduler 定时推送" 标记为 ✅ 已完成，移除其中关于群机器人 webhook 的描述。

- [ ] **Step 5: Update `docs/agent/active-context.md`**

更新 What Is Implemented 列表：
- 添加 "智能机器人 WebSocket 长连接模式（替代 HTTP 回调）"
- 添加 "APScheduler 定时 LLM 推送（可配置 cron/目标/内容）"
- 移除 "群机器人 webhook 推送客户端"相关描述

- [ ] **Step 6: Commit**

```bash
git add docs/
git commit -m "docs: update config, decisions, roadmap, and active-context for long-connection mode"
```

---

### Task 11: 最终验证

- [ ] **Step 1: 确认无遗漏的 import 引用**

```bash
grep -r "robot_router\|webhook\|WechatWebhookClient\|create_robot_router" src/ --include="*.py" | grep -v __pycache__
```

期望: 无输出（确认所有旧引用已清理）

- [ ] **Step 2: 运行完整测试套件**

```bash
uv run pytest -v
```

期望: 全部通过

- [ ] **Step 3: 验证应用启动**

```bash
timeout 3 uv run uvicorn src.main:app 2>&1 || true
```

期望: 正常启动，无错误

- [ ] **Step 4: Commit 最后的修正**

```bash
git add -A
git commit -m "chore: final cleanup after long-connection migration"
```

---

## 变更摘要

| 文件 | 操作 |
|------|------|
| `pyproject.toml` | 修改 (+websockets) |
| `src/config.py` | 修改 (新字段替换旧字段) |
| `src/main.py` | 修改 (lifespan 集成 WS + scheduler) |
| `src/wechat/ws_client.py` | **新增** |
| `src/wechat/message_handler.py` | **新增** |
| `src/wechat/__init__.py` | 修改 (更新导出) |
| `src/wechat/robot_router.py` | **删除** |
| `src/wechat/webhook.py` | **删除** |
| `src/scheduler/__init__.py` | **新增** |
| `tests/test_ws_client.py` | **新增** |
| `tests/test_scheduler.py` | **新增** |
| `tests/test_message_handler.py` | **新增** |
| `tests/test_wechat_robot_router.py` | **删除** |
| `tests/test_wechat_webhook.py` | **删除** |
| `.env.example` | 修改 |
| `docs/agent/config-variables.md` | 修改 |
| `docs/agent/decisions.md` | 修改 |
| `docs/agent/upgrade-roadmap.md` | 修改 |
| `docs/agent/active-context.md` | 修改 |
