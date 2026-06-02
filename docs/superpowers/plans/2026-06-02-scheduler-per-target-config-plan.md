# Scheduler Per-Target Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持 SCHEDULER 四个字段以 `|` 分隔配置多目标，每个目标独立指定 message 和 intent（intent 为空时走 IntentRouter 自动判定）。

**Architecture:** SchedulerManager 解析 `|` 分隔符将四个字段按位置配对存入 `_targets`（4 元组）；`_scheduled_push` 遍历时对 intent 为空的目标调用 intent_router.route() 自动判定意图。

**Tech Stack:** Python 3.13, pytest, AsyncMock

---

### Task 1: 修改分隔符和 per-target 解析

**Files:**
- Modify: `src/scheduler/__init__.py`（全量重写）

- [ ] **Step 1: 更新 `__init__` 解析逻辑**

将分隔符从 `,` 改为 `|`；新增 message 和 intent 的 per-target 解析；`_targets` 从 2 元组改为 4 元组。

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
        intent_router=None,
    ):
        """初始化调度管理器

        参数:
            ws_client: WeComWSClient 实例，用于推送消息
            agent_registry: AgentRegistry 实例
            cron_expression: cron 表达式（如 "0 9 * * *"）
            target_type: 推送目标类型，| 分隔多个值（如 "single|group"）
            target_id: 推送目标 ID，| 分隔多个值（如 "user1|chatid1"）
            message: 触发消息，| 分隔多个值（单值共享所有目标）
            intent: agent intent 标识，| 分隔多个值（空位走自动路由）
            db_session_factory: 异步数据库会话工厂
            intent_router: IntentRouter 实例，intent 为空时自动判定
        """
        self._ws = ws_client
        self._agent_registry = agent_registry
        self._cron = cron_expression
        self._db_session_factory = db_session_factory
        self._scheduler = AsyncIOScheduler()
        self._intent_router = intent_router

        # 解析 | 分隔的多目标配置，按位置配对
        types = [t.strip() for t in target_type.split("|") if t.strip()]
        ids = [i.strip() for i in target_id.split("|") if i.strip()]
        if len(types) != len(ids):
            raise ValueError(
                f"SCHEDULER_TARGET_TYPE 与 SCHEDULER_TARGET_ID 数量不匹配: "
                f"{len(types)} 个类型 vs {len(ids)} 个 ID"
            )
        if not types:
            raise ValueError("SCHEDULER_TARGET_ID 不能为空")
        n = len(types)

        # 解析 messages：单值广播，多值须匹配
        raw_msgs = [m.strip() for m in message.split("|") if m.strip()]
        if len(raw_msgs) == 1:
            messages = raw_msgs * n
        elif len(raw_msgs) == n:
            messages = raw_msgs
        else:
            raise ValueError(
                f"SCHEDULER_MESSAGE 数量不匹配: "
                f"{len(raw_msgs)} 个消息 vs {n} 个目标（应为 1 或 {n}）"
            )

        # 解析 intents：空字符串表示自动路由，单值广播，多值须匹配
        if not intent or not intent.strip():
            intents = [""] * n
        else:
            raw_intents = [i.strip() for i in intent.split("|")]
            if len(raw_intents) == 1:
                intents = raw_intents * n
            elif len(raw_intents) == n:
                intents = raw_intents
            else:
                raise ValueError(
                    f"SCHEDULER_INTENT 数量不匹配: "
                    f"{len(raw_intents)} 个 intent vs {n} 个目标（应为 1 或 {n}）"
                )

        self._targets = list(zip(types, ids, messages, intents))

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
            "Scheduler: started, cron=%s, targets=%s",
            self._cron, [(t, i, m, it) for t, i, m, it in self._targets],
        )

    def shutdown(self):
        """关闭调度器"""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler: shutdown")

    async def _scheduled_push(self):
        """定时推送 job：遍历所有目标，每个目标独立处理消息和 intent"""
        if self._ws is None:
            logger.error("Scheduler: ws_client is None, cannot push")
            return
        async with self._db_session_factory() as db:
            for target_type, target_id, msg, intent in self._targets:
                try:
                    # 解析 intent：有值直接用，为空走路由
                    resolved_intent = intent
                    if not resolved_intent and self._intent_router is not None:
                        resolved_intent, _ = await self._intent_router.route(msg)

                    agent = self._agent_registry.get(resolved_intent)
                    if agent is None:
                        logger.error(
                            "Scheduler: agent not found for intent=%s, skip %s=%s",
                            resolved_intent, target_type, target_id,
                        )
                        continue

                    result = await agent.handle(
                        intent=resolved_intent,
                        message=msg,
                        user_id=target_id,
                        db=db,
                        extra_state={"chat_type": target_type},
                    )
                    await self._ws.push_message(
                        target_type=target_type,
                        target_id=target_id,
                        msgtype="markdown",
                        content=result.reply,
                    )
                    logger.info(
                        "Scheduler: pushed to %s=%s, intent=%s, reply=%s",
                        target_type, target_id, resolved_intent, result.reply[:100],
                    )
                    await db.commit()
                except Exception as e:
                    logger.exception(
                        "Scheduler: push to %s=%s failed: %s",
                        target_type, target_id, e,
                    )
                    await db.rollback()
```

- [ ] **Step 2: 运行所有测试确认旧测试失败**

```bash
uv run pytest tests/test_scheduler.py -x -q
```
预期：失败，因为分隔符从 `,` 变为 `|`，且 `_targets` 结构改变。

---

### Task 2: 更新测试

**Files:**
- Modify: `tests/test_scheduler.py`（全量重写）

- [ ] **Step 1: 重写所有测试用例**

将分隔符 `,` 改为 `|`，`_targets` 断言适配 4 元组，新增 intent_router 自动路由测试。

```python
"""
调度器测试
测试 SchedulerManager 的创建、job 触发和推送逻辑
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


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


@pytest.fixture
def mock_router():
    """创建 mock IntentRouter"""
    router = AsyncMock()
    router.route.return_value = ("qa", 1.0)
    return router


@pytest.mark.asyncio
async def test_scheduler_creation(mock_ws, mock_registry, mock_db_factory):
    """验证 SchedulerManager 创建不报错，单目标单值保持兼容"""
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
    assert mgr._targets == [("single", "user1", "今日训练建议", "today_plan")]


@pytest.mark.asyncio
async def test_scheduled_push_calls_agent_and_pushes(mock_ws, mock_registry, mock_db_factory):
    """验证 _scheduled_push 调用 agent 并推送结果"""
    from src.scheduler import SchedulerManager
    from src.schemas.response import AgentResponse
    from unittest.mock import AsyncMock

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

    mock_agent.handle.assert_called_once()
    call_kwargs = mock_agent.handle.call_args.kwargs
    assert call_kwargs["intent"] == "today_plan"
    assert call_kwargs["message"] == "今日训练建议"
    assert call_kwargs["user_id"] == "user1"

    mock_ws.push_message.assert_called_once_with(
        target_type="single",
        target_id="user1",
        msgtype="markdown",
        content="今日训练计划：练肩 + 哑铃推举",
    )


@pytest.mark.asyncio
async def test_scheduled_push_handles_agent_not_found(mock_ws, mock_registry, mock_db_factory):
    """验证 agent 未注册时不崩溃，跳过该目标"""
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


@pytest.mark.asyncio
async def test_scheduler_multi_target_parsing(mock_ws, mock_registry, mock_db_factory):
    """验证多目标 | 分隔解析，message 单值广播，intent 单值广播"""
    from src.scheduler import SchedulerManager

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single|single|group",
        target_id="user1|user2|chatid1",
        message="test",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )
    assert mgr._targets == [
        ("single", "user1", "test", "today_plan"),
        ("single", "user2", "test", "today_plan"),
        ("group", "chatid1", "test", "today_plan"),
    ]


@pytest.mark.asyncio
async def test_scheduler_multi_target_count_mismatch(mock_ws, mock_registry, mock_db_factory):
    """验证类型和 ID 数量不匹配时抛出 ValueError"""
    from src.scheduler import SchedulerManager

    with pytest.raises(ValueError, match="数量不匹配"):
        SchedulerManager(
            ws_client=mock_ws,
            agent_registry=mock_registry,
            cron_expression="0 9 * * *",
            target_type="single|single",
            target_id="user1",
            message="test",
            intent="today_plan",
            db_session_factory=mock_db_factory,
        )


@pytest.mark.asyncio
async def test_scheduler_multi_target_empty_id(mock_ws, mock_registry, mock_db_factory):
    """验证空目标 ID 时抛出 ValueError"""
    from src.scheduler import SchedulerManager

    with pytest.raises(ValueError, match="不能为空"):
        SchedulerManager(
            ws_client=mock_ws,
            agent_registry=mock_registry,
            cron_expression="0 9 * * *",
            target_type="",
            target_id="",
            message="test",
            intent="today_plan",
            db_session_factory=mock_db_factory,
        )


@pytest.mark.asyncio
async def test_scheduled_push_multi_target(mock_ws, mock_registry, mock_db_factory):
    """验证多目标推送：每个目标独立调用 agent.handle 和 push_message"""
    from src.scheduler import SchedulerManager
    from src.schemas.response import AgentResponse
    from unittest.mock import AsyncMock

    mock_agent = AsyncMock()
    mock_agent.handle.return_value = AgentResponse(
        reply="今日训练计划",
        data=None,
    )
    mock_registry.register("today_plan", mock_agent)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single|group",
        target_id="user1|chatid1",
        message="今日训练建议",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )

    await mgr._scheduled_push()

    assert mock_agent.handle.call_count == 2
    assert mock_agent.handle.call_args_list[0].kwargs["user_id"] == "user1"
    assert mock_agent.handle.call_args_list[0].kwargs["extra_state"] == {"chat_type": "single"}
    assert mock_agent.handle.call_args_list[1].kwargs["user_id"] == "chatid1"
    assert mock_agent.handle.call_args_list[1].kwargs["extra_state"] == {"chat_type": "group"}

    assert mock_ws.push_message.call_count == 2
    mock_ws.push_message.assert_any_call(
        target_type="single", target_id="user1",
        msgtype="markdown", content="今日训练计划",
    )
    mock_ws.push_message.assert_any_call(
        target_type="group", target_id="chatid1",
        msgtype="markdown", content="今日训练计划",
    )


@pytest.mark.asyncio
async def test_scheduler_per_target_message(mock_ws, mock_registry, mock_db_factory):
    """验证每个目标使用不同的消息"""
    from src.scheduler import SchedulerManager
    from src.schemas.response import AgentResponse
    from unittest.mock import AsyncMock

    mock_agent = AsyncMock()
    mock_agent.handle.return_value = AgentResponse(reply="OK", data=None)
    mock_registry.register("today_plan", mock_agent)
    mock_registry.register("make_meal_plan", mock_agent)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single|single",
        target_id="user1|user2",
        message="今日训练建议|今天吃什么？",
        intent="today_plan|make_meal_plan",
        db_session_factory=mock_db_factory,
    )

    await mgr._scheduled_push()

    assert mock_agent.handle.call_count == 2
    # 第一个目标：训练建议
    assert mock_agent.handle.call_args_list[0].kwargs["message"] == "今日训练建议"
    assert mock_agent.handle.call_args_list[0].kwargs["intent"] == "today_plan"
    assert mock_agent.handle.call_args_list[0].kwargs["user_id"] == "user1"
    # 第二个目标：饮食建议
    assert mock_agent.handle.call_args_list[1].kwargs["message"] == "今天吃什么？"
    assert mock_agent.handle.call_args_list[1].kwargs["intent"] == "make_meal_plan"
    assert mock_agent.handle.call_args_list[1].kwargs["user_id"] == "user2"


@pytest.mark.asyncio
async def test_scheduler_intent_auto_routing(mock_ws, mock_registry, mock_db_factory, mock_router):
    """验证 intent 为空时走 IntentRouter 自动判定"""
    from src.scheduler import SchedulerManager
    from src.schemas.response import AgentResponse
    from unittest.mock import AsyncMock

    mock_agent = AsyncMock()
    mock_agent.handle.return_value = AgentResponse(reply="回答", data=None)
    mock_registry.register("qa", mock_agent)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single|single",
        target_id="user1|user2",
        message="今天练什么？|今天吃什么？",
        intent="|",
        db_session_factory=mock_db_factory,
        intent_router=mock_router,
    )

    await mgr._scheduled_push()

    # intent_router 被调用了两次（每个目标都走了路由）
    assert mock_router.route.call_count == 2
    mock_router.route.assert_any_call("今天练什么？")
    mock_router.route.assert_any_call("今天吃什么？")

    # agent.handle 被调用，intent 是 router 返回的 "qa"
    assert mock_agent.handle.call_count == 2
    assert mock_agent.handle.call_args_list[0].kwargs["message"] == "今天练什么？"
    assert mock_agent.handle.call_args_list[1].kwargs["message"] == "今天吃什么？"


@pytest.mark.asyncio
async def test_scheduler_message_count_mismatch(mock_ws, mock_registry, mock_db_factory):
    """验证 message 数量与目标数不匹配时抛出 ValueError（非单值情况）"""
    from src.scheduler import SchedulerManager

    with pytest.raises(ValueError, match="SCHEDULER_MESSAGE"):
        SchedulerManager(
            ws_client=mock_ws,
            agent_registry=mock_registry,
            cron_expression="0 9 * * *",
            target_type="single|single",
            target_id="user1|user2",
            message="msg1|msg2|msg3",
            intent="",
            db_session_factory=mock_db_factory,
        )


@pytest.mark.asyncio
async def test_scheduler_intent_count_mismatch(mock_ws, mock_registry, mock_db_factory):
    """验证 intent 数量与目标数不匹配时抛出 ValueError（非空非单值情况）"""
    from src.scheduler import SchedulerManager

    with pytest.raises(ValueError, match="SCHEDULER_INTENT"):
        SchedulerManager(
            ws_client=mock_ws,
            agent_registry=mock_registry,
            cron_expression="0 9 * * *",
            target_type="single|single",
            target_id="user1|user2",
            message="test",
            intent="a|b|c",
            db_session_factory=mock_db_factory,
        )
```

- [ ] **Step 2: 运行测试确认全部通过**

```bash
uv run pytest tests/test_scheduler.py -x -q
```
预期：14 passed

- [ ] **Step 3: Commit**

```bash
git add src/scheduler/__init__.py tests/test_scheduler.py
git commit -m "feat: scheduler per-target message and intent with auto-routing"
```

---

### Task 3: 更新 main.py 传入 intent_router

**Files:**
- Modify: `src/main.py:117-132`

- [ ] **Step 1: 添加 `intent_router` 参数**

在 `main.py` 的 `SchedulerManager` 构造调用中增加一行：

找到这段代码（约第 121-130 行）：
```python
        scheduler = SchedulerManager(
            ws_client=app.state.ws_client,
            agent_registry=agent_registry,
            cron_expression=settings.scheduler_cron,
            target_type=settings.scheduler_target_type,
            target_id=settings.scheduler_target_id,
            message=settings.scheduler_message,
            intent=settings.scheduler_intent,
            db_session_factory=async_session,
        )
```

在 `db_session_factory=async_session,` 之前增加一行：
```python
            intent_router=intent_router,
```

完整变为：
```python
        scheduler = SchedulerManager(
            ws_client=app.state.ws_client,
            agent_registry=agent_registry,
            cron_expression=settings.scheduler_cron,
            target_type=settings.scheduler_target_type,
            target_id=settings.scheduler_target_id,
            message=settings.scheduler_message,
            intent=settings.scheduler_intent,
            db_session_factory=async_session,
            intent_router=intent_router,
        )
```

- [ ] **Step 2: 运行全部测试确认无回归**

```bash
uv run pytest tests/ -x -q
```
预期：全部通过

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: pass intent_router to SchedulerManager for auto-routing"
```

---

### Task 4: 更新文档和示例配置

**Files:**
- Modify: `docs/agent/config-variables.md`
- Modify: `docs/agent/active-context.md`
- Modify: `.env.example`

- [ ] **Step 1: 更新 config-variables.md**

将 `SCHEDULER_TARGET_TYPE`、`SCHEDULER_TARGET_ID`、`SCHEDULER_MESSAGE`、`SCHEDULER_INTENT` 的描述更新为 `|` 分隔：

`docs/agent/config-variables.md` 中替换表格行：

```
| `SCHEDULER_TARGET_TYPE` | No | `"single"` | 推送目标类型，支持 `|` 分隔多个值：`single`（单聊）/ `group`（群聊） |
| `SCHEDULER_TARGET_ID` | No | `""` | 推送目标 ID，支持 `|` 分隔多个值。单聊时为 `userid`，群聊时为 `chatid`，按位置与 TARGET_TYPE 配对 |
| `SCHEDULER_MESSAGE` | No | `""` | 定时触发消息文本，支持 `|` 分隔多个值。单值共享所有目标，多值时须与目标数一致 |
| `SCHEDULER_INTENT` | No | `""` | 可选。支持 `|` 分隔多个值。有值走指定 agent，空位由 IntentRouter 自动判定。全空时所有目标均自动路由 |
```

替换末尾示例：

```env
# 单目标（与原有格式兼容）
SCHEDULER_CRON=0 9 * * 1-5
SCHEDULER_TARGET_TYPE=single
SCHEDULER_TARGET_ID=AssLe
SCHEDULER_MESSAGE=早安！今天我该做什么训练？
SCHEDULER_INTENT=

# 多目标：每人不同消息 + 混合指定/自动 intent
SCHEDULER_CRON=0 9 * * *
SCHEDULER_TARGET_TYPE=single|single|group
SCHEDULER_TARGET_ID=AssLe|ZhangSan|chatid123456
SCHEDULER_MESSAGE=今日训练建议|今天吃什么？|总结一下最近群聊重点
SCHEDULER_INTENT=today_plan||summarize_group
```

- [ ] **Step 2: 更新 .env.example**

```env
# APScheduler 定时推送配置（通过智能机器人长连接主动推送 LLM 生成的内容）
# 需要先配置 WECOM_AIBOT_BOT_ID 才会生效
# 四个字段均支持 | 分隔多个值，按位置配对（TYPE/ID/MESSAGE 数量必须一致，INTENT 空位走自动路由）
# 单目标示例: TARGET_TYPE=single, TARGET_ID=AssLe, MESSAGE=今日训练建议, INTENT=
# 多目标示例: TARGET_TYPE=single|group, TARGET_ID=AssLe|chatid123, MESSAGE=练什么？|吃什么？, INTENT=today_plan|
SCHEDULER_CRON=0 9 * * *
SCHEDULER_TARGET_TYPE=single
SCHEDULER_TARGET_ID=
SCHEDULER_MESSAGE=今日训练建议
SCHEDULER_INTENT=today_plan
```

- [ ] **Step 3: 更新 active-context.md**

将该行：
```
Config: `WECOM_AIBOT_BOT_ID` + `WECOM_AIBOT_SECRET` for intelligent robot WebSocket long-connection mode; `SCHEDULER_CRON`/`SCHEDULER_TARGET_TYPE`/`SCHEDULER_TARGET_ID`(支持逗号分隔多目标)/`SCHEDULER_MESSAGE`/`SCHEDULER_INTENT` for APScheduler timed push; ...
```

改为：
```
Config: `WECOM_AIBOT_BOT_ID` + `WECOM_AIBOT_SECRET` for intelligent robot WebSocket long-connection mode; `SCHEDULER_*` 系列字段支持 `|` 分隔多目标+独立消息+混合指定/自动 intent，通过 IntentRouter 自动路由; ...
```

- [ ] **Step 4: Commit**

```bash
git add docs/agent/config-variables.md docs/agent/active-context.md .env.example
git commit -m "docs: update scheduler config docs for pipe-delimited per-target format"
```

---

### Task 5: 补充 ADR

**Files:**
- Modify: `docs/agent/decisions.md`

- [ ] **Step 1: 在 ADR-013 末尾补充迭代说明**

在 ADR-013 的 Trade-off 行之后追加一段：

```markdown

### 迭代（2026-06-02）：扩展为按目标独立配置

ADR-013 的逗号分隔多目标方案进一步扩展：

- **分隔符改为 `|`**：避免英文逗号与消息文本潜在冲突。
- **MESSAGE 和 INTENT 独立配置**：每个目标可指定不同消息和 intent。MESSAGE 单值广播，多值按位置配对。INTENT 有值走指定 agent，空位走 IntentRouter 自动路由（规则 → LLM → unknown/QA 兜底）。
- **SchedulerManager 接收 IntentRouter**：intent 为空时调用 `intent_router.route(message)` 自动判定，不再强制 fallback 到 QA。

详见 `docs/superpowers/specs/2026-06-02-scheduler-per-target-config-design.md`。
```

- [ ] **Step 2: Commit**

```bash
git add docs/agent/decisions.md
git commit -m "docs: update ADR-013 with per-target config iteration"
```
