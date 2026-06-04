# Scenario Agent Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mixed all-purpose Butler/debug/intent/WS architecture with scene-specific agents for private chat, group mentions, and scheduled webhook composition.

**Architecture:** WeChat URL callback messages are normalized into `InboundMessage`, then dispatched by scene: private chat enters `PrivateButlerAgent`, group chat passes through `group_policy` before `GroupMentionAgent`, and scheduler webhook jobs call `WebhookComposerAgent` directly. The old debug API, WebSocket compatibility path, global `src/intent/`, and old `src/agents/butler/` package are removed after the new paths are wired.

**Tech Stack:** Python 3.13+, FastAPI, LangGraph, LangChain tool calling, SQLAlchemy async, SQLite, Pydantic v2, uv, pytest.

---

## File Structure Map

Create:

- `src/messaging/__init__.py` — exports normalized message, dispatch result, dispatch function, and group policy helpers.
- `src/messaging/inbound.py` — converts WeChat callback dictionaries into `InboundMessage`.
- `src/messaging/group_policy.py` — saves group messages, cleans history, and decides whether a group message should reply.
- `src/messaging/dispatch.py` — sends normalized messages to the correct scene agent.
- `src/agents/private_butler/` — migrated private-chat version of current `src/agents/butler/`.
- `src/agents/group_mention/` — group mention classifier and restricted group reply agent.
- `src/agents/webhook_composer/` — scheduler-only markdown composer agent.
- `tests/test_messaging.py` — messaging normalization, policy, and dispatch tests.
- `tests/test_group_mention_agent.py` — group-only capability tests.
- `tests/test_webhook_composer_agent.py` — scheduler composer tests.

Modify:

- `src/main.py` — instantiate new scene agents, remove debug router and global intent wiring, pass scene agents to callback and scheduler.
- `src/wechat/callback_router.py` — remove `IntentRouter`/`AgentRegistry` parameters and pass scene agents into callback processing.
- `src/wechat/callback_handler.py` — become a thin normalization/dispatch/reply adapter.
- `src/scheduler/__init__.py` — remove old WS/intent auto-routing mode and call `WebhookComposerAgent`.
- `src/agents/__init__.py` — export new scene agents if this file currently exports agent symbols.
- `tests/test_aibot_callback.py` — update callback tests around dispatch instead of old ButlerAgent parameters.
- `tests/test_scheduler.py` — update scheduler tests around `WebhookComposerAgent`.
- `tests/test_butler_agent.py` and `tests/test_butler_tools.py` — rename imports and expectations to `private_butler`.
- `deployment-guide.en.md` and `部署指南.md` — remove debug endpoint guidance.
- `docs/agent/active-context.md` — update implemented architecture.
- `docs/agent/patterns.md` — add scene-first dispatch and group policy patterns.
- `docs/agent/decisions.md` — add ADR for scene-agent refactor and deletions.
- `docs/agent/config-variables.md` — remove stale debug/WS references.
- `docs/agent/troubleshooting.md` — remove or archive stale WS troubleshooting.
- `AGENTS.md` and `CLAUDE.md` — update only if root guidance changes, then keep byte-for-byte identical.

Delete:

- `src/agents/butler/`
- `src/intent/`
- `src/router/debug.py`
- `src/router/`
- `src/wechat/message_handler.py`
- `src/wechat/ws_client.py`
- `tests/test_api.py`
- `tests/test_intent.py`
- `tests/test_message_handler.py`
- `tests/test_ws_client.py`

Implementation note: the approved project instructions normally discourage test edits unless explicitly requested. This plan includes test edits because the approved spec explicitly requires deleting old architecture protections and adding scene-boundary verification.

---

### Task 1: Add Normalized Messaging Primitives

**Files:**
- Create: `src/messaging/inbound.py`
- Create: `src/messaging/__init__.py`
- Create: `tests/test_messaging.py`

- [ ] **Step 1: Write failing inbound normalization tests**

Add the following initial tests to `tests/test_messaging.py`:

```python
"""
消息场景分发测试
验证企业微信回调消息会先被规范化，再交给场景分发层处理。
"""
from src.messaging import InboundMessage


def test_inbound_message_from_text_callback():
    """验证文本回调会转换为统一入站消息对象"""
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
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_messaging.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.messaging'`.

- [ ] **Step 3: Implement `InboundMessage`**

Create `src/messaging/inbound.py`:

```python
"""
统一入站消息模型
把企业微信 URL 回调消息转换成场景分发层使用的统一结构。

Workflow:
1. callback_handler 接收已解析的企业微信消息体
2. InboundMessage.from_wecom_callback() 提取用户、群聊、文本和回复 URL
3. dispatch_message() 根据 chat_type 把消息交给对应场景 agent
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
    """统一入站消息对象"""

    source: str
    msg_id: str
    msg_type: str
    user_id: str
    content: str
    chat_type: str
    chat_id: str | None
    response_url: str | None
    raw: dict[str, Any]

    @classmethod
    def from_wecom_callback(cls, raw: dict[str, Any]) -> "InboundMessage":
        """从企业微信智能机器人回调消息体构造统一入站消息

        参数:
            raw: 已解密并提取 body 后的企业微信消息体

        返回:
            InboundMessage: 供场景分发层使用的统一消息对象
        """
        msg_type = str(raw.get("msgtype", "text") or "text")
        if msg_type == "voice":
            content = str(raw.get("voice", {}).get("content", "") or "")
        else:
            content = str(raw.get("text", {}).get("content", "") or "")

        chat_id = str(raw.get("chatid", "") or "").strip() or None
        return cls(
            source="wecom_callback",
            msg_id=str(raw.get("msgid", "") or ""),
            msg_type=msg_type,
            user_id=str(raw.get("from", {}).get("userid", "") or ""),
            content=content,
            chat_type=str(raw.get("chattype", "single") or "single"),
            chat_id=chat_id,
            response_url=str(raw.get("response_url", "") or "") or None,
            raw=raw,
        )
```

Create `src/messaging/__init__.py`:

```python
"""
消息场景分发包
集中管理入站消息规范化、群消息策略和私聊/群聊场景分发。
"""
from src.messaging.inbound import InboundMessage

__all__ = ["InboundMessage"]
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_messaging.py -q
```

Expected: PASS for the two inbound normalization tests.

- [ ] **Step 5: Commit**

```bash
git add src/messaging/inbound.py src/messaging/__init__.py tests/test_messaging.py
git commit -m "feat: add normalized inbound messages"
```

---

### Task 2: Add Group Policy

**Files:**
- Modify: `src/messaging/__init__.py`
- Create: `src/messaging/group_policy.py`
- Modify: `tests/test_messaging.py`

- [ ] **Step 1: Write failing group policy tests**

Append to `tests/test_messaging.py`:

```python
import pytest


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
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_messaging.py -q
```

Expected: FAIL with import error for `apply_group_policy`.

- [ ] **Step 3: Implement group policy**

Create `src/messaging/group_policy.py`:

```python
"""
群消息策略
统一负责群消息保存、历史清理和是否触发群聊机器人回复的判断。

Workflow:
1. dispatch_message() 收到 group 入站消息
2. apply_group_policy() 保存可用群消息到 group_messages
3. 根据关键词和消息内容决定是否进入 GroupMentionAgent
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.messaging.inbound import InboundMessage
from src.models.group_message import GroupMessage

SUMMARY_KEYWORDS = ("总结", "摘要", "概括", "汇总")
WEATHER_KEYWORDS = ("天气", "气温", "下雨", "降雨")
QUESTION_MARKERS = ("?", "？", "吗", "怎么", "如何", "为什么", "什么")


@dataclass(frozen=True)
class GroupPolicyDecision:
    """群消息策略判断结果"""

    should_reply: bool
    reason: str
    category: str | None = None


def classify_group_trigger(content: str) -> str | None:
    """根据群消息内容判断触发类别

    参数:
        content: 群消息文本内容

    返回:
        str | None: 触发类别；未触发返回 None
    """
    normalized = content.strip().lower()
    if not normalized:
        return None
    if any(keyword in normalized for keyword in SUMMARY_KEYWORDS):
        return "summarize_group"
    if any(keyword in normalized for keyword in WEATHER_KEYWORDS):
        return "weather_placeholder"
    if any(marker in normalized for marker in QUESTION_MARKERS):
        return "simple_qa"
    return None


async def apply_group_policy(
    message: InboundMessage,
    db: AsyncSession,
) -> GroupPolicyDecision:
    """保存群消息并判断是否需要回复

    参数:
        message: 统一入站消息对象
        db: SQLAlchemy 异步数据库会话

    返回:
        GroupPolicyDecision: 是否回复及触发类别
    """
    if not message.content.strip():
        return GroupPolicyDecision(False, "empty_content")
    if not message.chat_id:
        return GroupPolicyDecision(False, "missing_chat_id")

    await GroupMessage.save(
        db,
        message.chat_id,
        message.user_id,
        message.content,
        int(time.time()),
    )
    await GroupMessage.cleanup(db, message.chat_id, keep=200)

    category = classify_group_trigger(message.content)
    if category is None:
        return GroupPolicyDecision(False, "non_trigger")
    return GroupPolicyDecision(True, "trigger", category)
```

Update `src/messaging/__init__.py`:

```python
"""
消息场景分发包
集中管理入站消息规范化、群消息策略和私聊/群聊场景分发。
"""
from src.messaging.group_policy import (
    GroupPolicyDecision,
    apply_group_policy,
    classify_group_trigger,
)
from src.messaging.inbound import InboundMessage

__all__ = [
    "GroupPolicyDecision",
    "InboundMessage",
    "apply_group_policy",
    "classify_group_trigger",
]
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_messaging.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/messaging/group_policy.py src/messaging/__init__.py tests/test_messaging.py
git commit -m "feat: add group message policy"
```

---

### Task 3: Create GroupMentionAgent

**Files:**
- Create: `src/agents/group_mention/__init__.py`
- Create: `src/agents/group_mention/classifier.py`
- Create: `src/agents/group_mention/graph.py`
- Create: `src/agents/group_mention/nodes.py`
- Create: `src/agents/group_mention/prompts.py`
- Create: `src/agents/group_mention/state.py`
- Create: `tests/test_group_mention_agent.py`

- [ ] **Step 1: Write failing GroupMentionAgent tests**

Create `tests/test_group_mention_agent.py`:

```python
"""
群聊 @ 机器人 Agent 测试
验证群聊场景只允许总结、天气占位和简单问答，不暴露私聊训练/食谱能力。
"""
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_group_mention_rejects_training_request(db_session, mock_llm):
    """验证群聊里训练请求会被短拒绝"""
    from src.agents.group_mention import GroupMentionAgent

    summary_agent = AsyncMock()
    agent = GroupMentionAgent(llm_client=mock_llm, summary_agent=summary_agent)

    result = await agent.handle(
        "group_mention",
        "帮我制定今天训练计划",
        "user-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )

    assert "群聊里我只处理总结、天气和简单问答" in result.reply
    summary_agent.handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_mention_weather_placeholder(db_session, mock_llm):
    """验证天气查询第一阶段返回待配置占位回复"""
    from src.agents.group_mention import GroupMentionAgent

    agent = GroupMentionAgent(llm_client=mock_llm, summary_agent=AsyncMock())

    result = await agent.handle(
        "group_mention",
        "今天上海天气怎么样？",
        "user-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )

    assert "天气功能" in result.reply
    assert "数据源" in result.reply


@pytest.mark.asyncio
async def test_group_mention_summary_calls_summary_agent(db_session, mock_llm):
    """验证群总结请求会调用 SummaryAgent 的 summarize_group 能力"""
    from src.agents.group_mention import GroupMentionAgent

    summary_agent = AsyncMock()
    summary_agent.handle.return_value.reply = "这是群聊总结"
    summary_agent.handle.return_value.data = {"count": 3}
    agent = GroupMentionAgent(llm_client=mock_llm, summary_agent=summary_agent)

    result = await agent.handle(
        "group_mention",
        "总结一下",
        "user-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )

    assert result.reply == "这是群聊总结"
    assert result.data == {"count": 3}
    summary_agent.handle.assert_awaited_once_with(
        "summarize_group",
        "总结一下",
        "user-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )


@pytest.mark.asyncio
async def test_group_mention_simple_qa_uses_llm(db_session, mock_llm):
    """验证简单问答使用群聊轻量 prompt 直接回复"""
    from src.agents.group_mention import GroupMentionAgent

    mock_llm.chat.return_value = "可以，简单来说就是先验签再处理。"
    agent = GroupMentionAgent(llm_client=mock_llm, summary_agent=AsyncMock())

    result = await agent.handle(
        "group_mention",
        "URL 回调是什么？",
        "user-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )

    assert result.reply == "可以，简单来说就是先验签再处理。"
    mock_llm.chat.assert_awaited_once()
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_group_mention_agent.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.agents.group_mention'`.

- [ ] **Step 3: Implement GroupMentionAgent**

Create `src/agents/group_mention/state.py`:

```python
"""
群聊 @ Agent 状态定义
定义群聊受限场景中从分类到回复生成的状态字段。
"""
from typing import TypedDict


class GroupMentionState(TypedDict, total=False):
    """群聊 @ Agent 图状态"""

    intent: str
    message: str
    user_id: str
    chat_type: str
    chat_id: str | None
    category: str
    reply: str
    data: dict | None
    error: str | None
```

Create `src/agents/group_mention/classifier.py`:

```python
"""
群聊 @ 分类器
规则优先识别群聊总结、天气占位、简单问答和不支持能力。
"""
from __future__ import annotations

import json

SUMMARY_KEYWORDS = ("总结", "摘要", "概括", "汇总")
WEATHER_KEYWORDS = ("天气", "气温", "下雨", "降雨")
BLOCKED_KEYWORDS = ("训练", "打卡", "练什么", "食谱", "吃什么", "饮食", "餐")
QUESTION_MARKERS = ("?", "？", "吗", "怎么", "如何", "为什么", "什么")
ALLOWED_CATEGORIES = {
    "summarize_group",
    "weather_placeholder",
    "simple_qa",
    "unsupported",
}

CLASSIFIER_PROMPT = """你是群聊机器人意图分类器。只允许返回以下类别：
- summarize_group: 用户要求总结群聊
- weather_placeholder: 用户询问天气、气温、下雨等
- simple_qa: 简单问题或轻量问答
- unsupported: 训练、食谱、私密陪伴、复杂任务或无法判断

只返回 JSON：
{"category": "<category>"}"""


def classify_group_message_by_rules(message: str) -> str | None:
    """用确定性规则识别群聊消息类别

    参数:
        message: 群聊消息文本

    返回:
        str | None: 类别；规则未命中返回 None
    """
    normalized = message.strip().lower()
    if not normalized:
        return "unsupported"
    if any(keyword in normalized for keyword in SUMMARY_KEYWORDS):
        return "summarize_group"
    if any(keyword in normalized for keyword in WEATHER_KEYWORDS):
        return "weather_placeholder"
    if any(keyword in normalized for keyword in BLOCKED_KEYWORDS):
        return "unsupported"
    if any(marker in normalized for marker in QUESTION_MARKERS):
        return "simple_qa"
    return None


async def classify_group_message(message: str, llm_client) -> str:
    """规则优先、LLM 兜底分类群聊 @ 消息

    参数:
        message: 群聊消息文本
        llm_client: LLM 客户端，用于规则未命中时分类

    返回:
        str: 群聊场景类别
    """
    rule_match = classify_group_message_by_rules(message)
    if rule_match is not None:
        return rule_match
    try:
        raw = await llm_client.chat_json(
            messages=[
                {"role": "system", "content": CLASSIFIER_PROMPT},
                {"role": "user", "content": message},
            ],
        )
        category = json.loads(raw).get("category", "unsupported")
        if category in ALLOWED_CATEGORIES:
            return category
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return "unsupported"
```

Create `src/agents/group_mention/prompts.py`:

```python
"""
群聊 @ Agent 提示词
提供群聊轻量问答的 system prompt，避免私聊式长陪伴和越界能力。
"""

GROUP_QA_PROMPT = """你是群聊里的轻量助手。请简短回答简单问题。

边界：
- 不制定训练计划，不记录训练。
- 不制定食谱或饮食计划。
- 不做长篇情感陪伴。
- 不访问私人知识库。
- 如果问题超出群聊支持范围，请说明群聊里只处理总结、天气和简单问答。
"""
```

Create `src/agents/group_mention/nodes.py`:

```python
"""
群聊 @ Agent 节点函数
实现分类、群总结、天气占位、简单问答和不支持能力回复。
"""
from src.agents.group_mention.classifier import classify_group_message
from src.agents.group_mention.prompts import GROUP_QA_PROMPT


async def classify_node(state: dict) -> dict:
    """分类群聊 @ 消息

    参数:
        state: 当前图状态

    返回:
        dict: 包含 category 的状态更新
    """
    llm = state["llm"]
    category = await classify_group_message(state.get("message", ""), llm)
    return {"category": category}


def route_by_category(state: dict) -> str:
    """根据分类结果选择下一个节点

    参数:
        state: 当前图状态

    返回:
        str: 下一个节点名
    """
    category = state.get("category", "unsupported")
    if category in {"summarize_group", "weather_placeholder", "simple_qa"}:
        return category
    return "unsupported"


async def summarize_group_node(state: dict) -> dict:
    """调用 SummaryAgent 总结当前群聊

    参数:
        state: 当前图状态

    返回:
        dict: 回复和数据
    """
    result = await state["summary_agent"].handle(
        "summarize_group",
        state.get("message", ""),
        state.get("user_id", ""),
        state["db"],
        extra_state={
            "chat_type": state.get("chat_type", "group"),
            "chat_id": state.get("chat_id"),
        },
    )
    return {"reply": result.reply, "data": result.data}


async def weather_placeholder_node(state: dict) -> dict:
    """返回天气功能待配置提示

    参数:
        state: 当前图状态

    返回:
        dict: 天气占位回复
    """
    return {"reply": "天气功能还没有接入数据源，配置完成后我就能查询。"}


async def simple_qa_node(state: dict) -> dict:
    """生成群聊简单问答回复

    参数:
        state: 当前图状态

    返回:
        dict: 简单问答回复
    """
    reply = await state["llm"].chat(
        messages=[
            {"role": "system", "content": GROUP_QA_PROMPT},
            {"role": "user", "content": state.get("message", "")},
        ]
    )
    return {"reply": reply}


async def unsupported_node(state: dict) -> dict:
    """返回群聊不支持能力的短提示

    参数:
        state: 当前图状态

    返回:
        dict: 不支持能力回复
    """
    return {"reply": "群聊里我只处理总结、天气和简单问答，训练和食谱请私聊我。"}
```

Create `src/agents/group_mention/graph.py`:

```python
"""
群聊 @ Agent 图组装
构建只允许群总结、天气占位和简单问答的受限群聊 StateGraph。
"""
from langgraph.graph import END, START, StateGraph

from src.agents.group_mention.nodes import (
    classify_node,
    route_by_category,
    simple_qa_node,
    summarize_group_node,
    unsupported_node,
    weather_placeholder_node,
)
from src.agents.group_mention.state import GroupMentionState
from src.schemas.response import AgentResponse


class GroupMentionAgent:
    """群聊 @ 机器人场景 agent"""

    def __init__(self, llm_client, summary_agent):
        """初始化群聊 @ agent

        参数:
            llm_client: LLM 客户端
            summary_agent: 群聊总结领域 agent
        """
        self._llm = llm_client
        self._summary_agent = summary_agent
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建群聊 @ StateGraph

        参数:
            无

        返回:
            CompiledStateGraph: 编译后的图
        """
        builder = StateGraph(GroupMentionState)
        builder.add_node("classify", classify_node)
        builder.add_node("summarize_group", summarize_group_node)
        builder.add_node("weather_placeholder", weather_placeholder_node)
        builder.add_node("simple_qa", simple_qa_node)
        builder.add_node("unsupported", unsupported_node)

        builder.add_edge(START, "classify")
        builder.add_conditional_edges(
            "classify",
            route_by_category,
            {
                "summarize_group": "summarize_group",
                "weather_placeholder": "weather_placeholder",
                "simple_qa": "simple_qa",
                "unsupported": "unsupported",
            },
        )
        builder.add_edge("summarize_group", END)
        builder.add_edge("weather_placeholder", END)
        builder.add_edge("simple_qa", END)
        builder.add_edge("unsupported", END)
        return builder.compile()

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理群聊 @ 消息

        参数:
            intent: 场景意图，通常为 group_mention
            message: 群聊消息文本
            user_id: 发送者用户 ID
            db: 数据库会话
            extra_state: chat_type/chat_id 等群聊上下文

        返回:
            AgentResponse: 群聊回复
        """
        extra_state = extra_state or {}
        initial_state = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "chat_type": extra_state.get("chat_type", "group"),
            "chat_id": extra_state.get("chat_id"),
            "llm": self._llm,
            "summary_agent": self._summary_agent,
            "db": db,
        }
        try:
            result = await self._graph.ainvoke(initial_state)
            return AgentResponse(
                reply=result.get("reply", "") or "群聊回复生成失败，请稍后再试。",
                data=result.get("data"),
            )
        except Exception:
            return AgentResponse(reply="群聊服务暂时不可用，请稍后再试。")
```

Create `src/agents/group_mention/__init__.py`:

```python
"""
群聊 @ 机器人场景 agent
只处理群聊总结、天气占位和简单问答。
"""
from src.agents.group_mention.graph import GroupMentionAgent

__all__ = ["GroupMentionAgent"]
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_group_mention_agent.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agents/group_mention tests/test_group_mention_agent.py
git commit -m "feat: add group mention agent"
```

---

### Task 4: Create WebhookComposerAgent

**Files:**
- Create: `src/agents/webhook_composer/__init__.py`
- Create: `src/agents/webhook_composer/graph.py`
- Create: `src/agents/webhook_composer/nodes.py`
- Create: `src/agents/webhook_composer/prompts.py`
- Create: `src/agents/webhook_composer/state.py`
- Create: `tests/test_webhook_composer_agent.py`

- [ ] **Step 1: Write failing WebhookComposerAgent tests**

Create `tests/test_webhook_composer_agent.py`:

```python
"""
群 webhook 内容生成 Agent 测试
验证定时推送只生成最终 markdown 正文，不走私聊或群聊工具。
"""
import pytest


@pytest.mark.asyncio
async def test_webhook_composer_generates_markdown_body(db_session, mock_llm):
    """验证 webhook composer 只返回模型生成的群通知正文"""
    from src.agents.webhook_composer import WebhookComposerAgent

    mock_llm.chat.return_value = "## 早安\n今天记得准时出门。"
    agent = WebhookComposerAgent(llm_client=mock_llm)

    result = await agent.handle(
        "webhook_compose",
        "生成早安提醒",
        "fitness-group",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "fitness-group"},
    )

    assert result.reply == "## 早安\n今天记得准时出门。"
    assert result.data == {"intent": "webhook_compose"}
    mock_llm.chat.assert_awaited_once()
    messages = mock_llm.chat.await_args.kwargs["messages"]
    assert "只生成最终要发到群里的 markdown 正文" in messages[0]["content"]


@pytest.mark.asyncio
async def test_webhook_composer_fallback_on_empty_reply(db_session, mock_llm):
    """验证空回复会降级为安全正文"""
    from src.agents.webhook_composer import WebhookComposerAgent

    mock_llm.chat.return_value = ""
    agent = WebhookComposerAgent(llm_client=mock_llm)

    result = await agent.handle(
        "webhook_compose",
        "提醒大家喝水",
        "group-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "group-a"},
    )

    assert result.reply == "提醒大家喝水"
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_webhook_composer_agent.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.agents.webhook_composer'`.

- [ ] **Step 3: Implement WebhookComposerAgent**

Create `src/agents/webhook_composer/state.py`:

```python
"""
Webhook 内容生成 Agent 状态定义
定义定时群推送正文生成所需字段。
"""
from typing import TypedDict


class WebhookComposerState(TypedDict, total=False):
    """WebhookComposerAgent 状态"""

    intent: str
    message: str
    user_id: str
    chat_type: str
    chat_id: str | None
    reply: str
    error: str | None
```

Create `src/agents/webhook_composer/prompts.py`:

```python
"""
Webhook 内容生成提示词
约束模型只生成即将发送到群 webhook 的 markdown 正文。
"""

WEBHOOK_COMPOSER_PROMPT = """这是 APScheduler 定时群 webhook 推送任务。

系统会负责通过企业微信群 webhook 自动发送，你只生成最终要发到群里的 markdown 正文。

规则：
- 不要解释执行方式。
- 不要说自己没有群发权限。
- 不要给用户手动复制粘贴步骤。
- 不要调用或假装调用训练、食谱、问答、天气、群总结能力。
- 正文应适合直接作为企业微信群 markdown 发送。
"""
```

Create `src/agents/webhook_composer/nodes.py`:

```python
"""
Webhook 内容生成节点函数
调用 LLM 将配置指令转换成最终群 markdown 正文。
"""
from src.agents.webhook_composer.prompts import WEBHOOK_COMPOSER_PROMPT


async def compose_webhook_body(state: dict) -> dict:
    """生成 webhook 推送正文

    参数:
        state: 当前图状态，包含 llm 和 message

    返回:
        dict: 包含 reply 的状态更新
    """
    message = state.get("message", "")
    reply = await state["llm"].chat(
        messages=[
            {"role": "system", "content": WEBHOOK_COMPOSER_PROMPT},
            {"role": "user", "content": f"配置指令：{message}"},
        ]
    )
    return {"reply": reply.strip() or message}
```

Create `src/agents/webhook_composer/graph.py`:

```python
"""
Webhook 内容生成 Agent 图组装
构建 scheduler 专用 agent，用于生成最终群 markdown 正文。
"""
from langgraph.graph import END, START, StateGraph

from src.agents.webhook_composer.nodes import compose_webhook_body
from src.agents.webhook_composer.state import WebhookComposerState
from src.schemas.response import AgentResponse


class WebhookComposerAgent:
    """群 webhook 定时推送正文生成 agent"""

    def __init__(self, llm_client):
        """初始化 WebhookComposerAgent

        参数:
            llm_client: LLM 客户端
        """
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建 StateGraph

        参数:
            无

        返回:
            CompiledStateGraph: 编译后的图
        """
        builder = StateGraph(WebhookComposerState)
        builder.add_node("compose", compose_webhook_body)
        builder.add_edge(START, "compose")
        builder.add_edge("compose", END)
        return builder.compile()

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """生成群 webhook 推送正文

        参数:
            intent: 场景意图，通常为 webhook_compose
            message: scheduler target 配置指令
            user_id: 目标群或任务名称
            db: 数据库会话，当前不直接使用
            extra_state: chat_type/chat_id 等上下文

        返回:
            AgentResponse: 适合直接推送的 markdown 正文
        """
        extra_state = extra_state or {}
        initial_state = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "chat_type": extra_state.get("chat_type", "group"),
            "chat_id": extra_state.get("chat_id"),
            "llm": self._llm,
        }
        try:
            result = await self._graph.ainvoke(initial_state)
            return AgentResponse(
                reply=result.get("reply", "") or message,
                data={"intent": "webhook_compose"},
            )
        except Exception:
            return AgentResponse(reply=message, data={"intent": "webhook_compose"})
```

Create `src/agents/webhook_composer/__init__.py`:

```python
"""
群 webhook 定时推送正文生成 agent
只负责根据配置指令生成最终 markdown 正文。
"""
from src.agents.webhook_composer.graph import WebhookComposerAgent

__all__ = ["WebhookComposerAgent"]
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_webhook_composer_agent.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agents/webhook_composer tests/test_webhook_composer_agent.py
git commit -m "feat: add webhook composer agent"
```

---

### Task 5: Migrate ButlerAgent To PrivateButlerAgent

**Files:**
- Create: `src/agents/private_butler/`
- Modify: `tests/test_butler_agent.py`
- Modify: `tests/test_butler_tools.py`

- [ ] **Step 1: Write failing import compatibility changes in private butler tests**

Mechanically update imports in `tests/test_butler_agent.py` and `tests/test_butler_tools.py`:

```python
from src.agents.private_butler import PrivateButlerAgent
from src.agents.private_butler.tools import (
    PrivateButlerToolContext,
    create_private_butler_tools,
)
```

Replace class construction with the same dependency mocks already used by existing `ButlerAgent` tests:

```python
agent = PrivateButlerAgent(
    llm_client=mock_llm,
    fitness_agent=mock_fitness_agent,
    meal_agent=mock_meal_agent,
    summary_agent=mock_summary_agent,
    knowledge_service=mock_knowledge_service,
    web_search_service=mock_web_search_service,
)
```

Replace tool factory calls:

```python
context = PrivateButlerToolContext(
    fitness_agent=mock_fitness_agent,
    meal_agent=mock_meal_agent,
    summary_agent=mock_summary_agent,
    knowledge_service=mock_knowledge_service,
    web_search_service=mock_web_search_service,
)
tools = create_private_butler_tools(context)
```

Keep the existing behavior assertions: tool calling, training tool, meal tool, summary tool, local knowledge, and web search should still work for private chat.

- [ ] **Step 2: Run focused private-butler tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_butler_agent.py tests/test_butler_tools.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.agents.private_butler'`.

- [ ] **Step 3: Copy old ButlerAgent package into `private_butler`**

Run:

```bash
mkdir -p src/agents/private_butler
cp src/agents/butler/__init__.py src/agents/private_butler/__init__.py
cp src/agents/butler/graph.py src/agents/private_butler/graph.py
cp src/agents/butler/nodes.py src/agents/private_butler/nodes.py
cp src/agents/butler/prompts.py src/agents/private_butler/prompts.py
cp src/agents/butler/state.py src/agents/private_butler/state.py
cp src/agents/butler/tools.py src/agents/private_butler/tools.py
```

- [ ] **Step 4: Rename symbols and imports in private_butler files**

Apply these mechanical changes:

- In `src/agents/private_butler/graph.py`:
  - `ButlerAgent` -> `PrivateButlerAgent`
  - `ButlerState` -> `PrivateButlerState`
  - imports from `src.agents.butler.*` -> `src.agents.private_butler.*`
  - `ButlerToolContext` -> `PrivateButlerToolContext`
  - `create_butler_tools` -> `create_private_butler_tools`
  - `thread_id`: `f"butler:{user_id}"` -> `f"private_butler:{user_id}"`
  - returned data: `{"intent": "butler"}` -> `{"intent": "private_butler"}`

- In `src/agents/private_butler/tools.py`:
  - `ButlerToolContext` -> `PrivateButlerToolContext`
  - `create_butler_tools` -> `create_private_butler_tools`

- In `src/agents/private_butler/state.py`:
  - `ButlerState` -> `PrivateButlerState`

- In `src/agents/private_butler/prompts.py`:
  - Update the system prompt opening to explain this is the private-chat assistant:

```python
PRIVATE_BUTLER_SYSTEM_PROMPT = """你是"小管家"，用户私聊里的总控私人助理。

私聊场景允许你更自然、更有人味地对话。你可以直接聊天，也可以按需调用工具。请遵守以下策略：
- 用户只是寒暄、闲聊、表达状态或问简单常识时，直接回复，不要调用工具。
- 用户要记录训练、查询训练计划、做饮食计划、总结文本或总结群聊时，调用对应工具。
- 用户问本地资料、个人记录、群聊资料相关问题时，优先使用 search_local_knowledge。
- 用户明确需要最新信息、网页资料、实时新闻、热播内容或外部检索时，调用 search_web。
- 工具返回资料后，要用自然中文整合结果，不要暴露工具调用细节。
- 不确定、资料不足或工具无结果时，如实说明，不要编造。

历史摘要：
{conversation_summary}

最近对话：
{recent_messages}"""
```

- In `src/agents/private_butler/__init__.py`:

```python
"""
私聊小管家总控 agent
负责私聊场景中的自然对话和完整工具调用能力。
"""
from src.agents.private_butler.graph import PrivateButlerAgent

__all__ = ["PrivateButlerAgent"]
```

- [ ] **Step 5: Run private-butler tests and update any remaining old import paths**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_butler_agent.py tests/test_butler_tools.py -q
```

Expected: PASS after all `src.agents.butler` imports and symbol names are migrated.

- [ ] **Step 6: Commit**

```bash
git add src/agents/private_butler tests/test_butler_agent.py tests/test_butler_tools.py
git commit -m "feat: migrate butler to private chat agent"
```

---

### Task 6: Add Scene Dispatch

**Files:**
- Create: `src/messaging/dispatch.py`
- Modify: `src/messaging/__init__.py`
- Modify: `tests/test_messaging.py`

- [ ] **Step 1: Write failing dispatch tests**

Append to `tests/test_messaging.py`:

```python
from unittest.mock import AsyncMock


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
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_messaging.py -q
```

Expected: FAIL with import error for `dispatch_message`.

- [ ] **Step 3: Implement dispatch**

Create `src/messaging/dispatch.py`:

```python
"""
消息场景分发
根据统一入站消息的 chat_type 将消息交给私聊或群聊场景 agent。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.messaging.group_policy import apply_group_policy
from src.messaging.inbound import InboundMessage


@dataclass(frozen=True)
class DispatchResult:
    """消息分发结果"""

    should_reply: bool
    reply: str = ""
    data: dict | None = None
    reason: str = ""


async def dispatch_message(
    message: InboundMessage,
    db: AsyncSession,
    private_agent,
    group_agent,
) -> DispatchResult:
    """按场景分发入站消息

    参数:
        message: 统一入站消息
        db: SQLAlchemy 异步数据库会话
        private_agent: 私聊场景 agent
        group_agent: 群聊 @ 场景 agent

    返回:
        DispatchResult: 是否需要通过 response_url 回复及回复内容
    """
    if message.msg_type not in ("text", "voice"):
        return DispatchResult(True, "暂不支持该消息类型", reason="unsupported_msg_type")

    if message.chat_type == "group":
        decision = await apply_group_policy(message, db)
        if not decision.should_reply:
            return DispatchResult(False, reason=decision.reason)
        result = await group_agent.handle(
            "group_mention",
            message.content,
            message.user_id,
            db,
            extra_state={"chat_type": "group", "chat_id": message.chat_id},
        )
        return DispatchResult(True, result.reply, result.data, decision.reason)

    result = await private_agent.handle(
        "private_butler",
        message.content,
        message.user_id,
        db,
        extra_state={"chat_type": "single", "chat_id": message.chat_id},
    )
    return DispatchResult(True, result.reply, result.data, "private_chat")
```

Update `src/messaging/__init__.py`:

```python
"""
消息场景分发包
集中管理入站消息规范化、群消息策略和私聊/群聊场景分发。
"""
from src.messaging.dispatch import DispatchResult, dispatch_message
from src.messaging.group_policy import (
    GroupPolicyDecision,
    apply_group_policy,
    classify_group_trigger,
)
from src.messaging.inbound import InboundMessage

__all__ = [
    "DispatchResult",
    "GroupPolicyDecision",
    "InboundMessage",
    "apply_group_policy",
    "classify_group_trigger",
    "dispatch_message",
]
```

- [ ] **Step 4: Run focused tests and verify they pass**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_messaging.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/messaging/dispatch.py src/messaging/__init__.py tests/test_messaging.py
git commit -m "feat: add scene message dispatch"
```

---

### Task 7: Wire URL Callback To Scene Dispatch

**Files:**
- Modify: `src/wechat/callback_router.py`
- Modify: `src/wechat/callback_handler.py`
- Modify: `tests/test_aibot_callback.py`

- [ ] **Step 1: Update callback tests for scene agents**

In `tests/test_aibot_callback.py`, replace fixtures or mocks named `mock_butler_agent` with:

```python
mock_private_agent = AsyncMock()
mock_group_agent = AsyncMock()
```

For single chat callback tests, assert:

```python
mock_private_agent.handle.assert_awaited_once_with(
    "private_butler",
    "你好",
    "user-a",
    db_session,
    extra_state={"chat_type": "single", "chat_id": None},
)
```

For group non-trigger callback tests, assert:

```python
mock_group_agent.handle.assert_not_awaited()
```

For group trigger callback tests, assert:

```python
mock_group_agent.handle.assert_awaited_once_with(
    "group_mention",
    "总结一下",
    "user-a",
    db_session,
    extra_state={"chat_type": "group", "chat_id": "chat-1"},
)
```

Update `create_aibot_callback_router(...)` calls in tests to pass `private_agent=` and `group_agent=` instead of `intent_router=`, `agent_registry=`, and `butler_agent=`.

- [ ] **Step 2: Run callback tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_aibot_callback.py -q
```

Expected: FAIL because callback router/handler signatures still expect old dependencies.

- [ ] **Step 3: Change callback handler signature and implementation**

In `src/wechat/callback_handler.py`, replace old imports:

```python
from src.agents.butler import ButlerAgent
from src.agents.registry import AgentRegistry
from src.intent.router import IntentRouter
```

with:

```python
from src.messaging import InboundMessage, dispatch_message
```

Change `handle_callback_message(...)` signature to:

```python
async def handle_callback_message(
    msg: dict,
    reply_client: ResponseUrlReplyClient,
    private_agent,
    group_agent,
    db: AsyncSession,
):
```

Replace the body with:

```python
    inbound = InboundMessage.from_wecom_callback(msg)
    if inbound.msg_type == "voice" and not inbound.content:
        logger.info("AIBot callback: voice recognition empty, ignoring")
        return

    logger.info(
        "AIBot callback handler: msg_type=%s from_user=%s chat_type=%s chat_id=%s content=%s",
        inbound.msg_type,
        inbound.user_id,
        inbound.chat_type,
        inbound.chat_id,
        inbound.content[:200],
    )

    result = await dispatch_message(
        inbound,
        db,
        private_agent=private_agent,
        group_agent=group_agent,
    )
    if not result.should_reply:
        logger.info("AIBot callback: no reply, reason=%s", result.reason)
        return

    logger.info("AIBot callback handler: reply_text=%s", result.reply[:200])
    await reply_client.send_reply(inbound.response_url or "", result.reply)
```

Remove now-unused helper functions from `callback_handler.py`:

- `_extract_content`
- `_build_reply_text`
- `_is_summarize_trigger`
- `_SUMMARIZE_KEYWORDS`

- [ ] **Step 4: Change callback router dependency names**

In `src/wechat/callback_router.py`, remove `IntentRouter`, `AgentRegistry`, and `ButlerAgent` imports.

Change `create_aibot_callback_router(...)` signature to:

```python
def create_aibot_callback_router(
    token: str,
    encoding_aes_key: str,
    receive_id: str,
    private_agent,
    group_agent,
    db_session_factory,
    reply_client: ResponseUrlReplyClient | None = None,
) -> APIRouter:
```

Update `background_tasks.add_task(...)`:

```python
background_tasks.add_task(
    process_recorded_message,
    msg,
    reply_client,
    private_agent,
    group_agent,
    db_session_factory,
)
```

Change `process_recorded_message(...)` signature to:

```python
async def process_recorded_message(
    msg: dict,
    reply_client: ResponseUrlReplyClient,
    private_agent,
    group_agent,
    db_session_factory,
):
```

Update its call to `handle_callback_message(...)`:

```python
await handle_callback_message(
    msg,
    reply_client,
    private_agent,
    group_agent,
    db,
)
```

- [ ] **Step 5: Run callback tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_aibot_callback.py -q
```

Expected: PASS after tests and implementation agree.

- [ ] **Step 6: Commit**

```bash
git add src/wechat/callback_router.py src/wechat/callback_handler.py tests/test_aibot_callback.py
git commit -m "feat: route callbacks through scene dispatch"
```

---

### Task 8: Wire Scheduler To WebhookComposerAgent

**Files:**
- Modify: `src/scheduler/__init__.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Update scheduler tests to expect composer agent**

In `tests/test_scheduler.py`, update webhook target tests so `SchedulerManager` is constructed with:

```python
webhook_composer_agent=mock_composer_agent
```

Assert `_scheduled_webhook_push()` calls:

```python
mock_composer_agent.handle.assert_awaited_once_with(
    intent="webhook_compose",
    message=target.message,
    user_id=target.chat_id or target.name,
    db=db_session,
    extra_state={"chat_type": "group", "chat_id": target.chat_id or target.name},
)
```

Delete or rewrite scheduler tests whose only purpose is old `intent_router.route()` auto-routing. The new scheduler should not auto-route intent.

- [ ] **Step 2: Run scheduler tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_scheduler.py -q
```

Expected: FAIL because `SchedulerManager` does not yet accept `webhook_composer_agent`.

- [ ] **Step 3: Simplify SchedulerManager dependencies**

In `src/scheduler/__init__.py`, update `SchedulerManager.__init__`:

- Remove or deprecate constructor fields:
  - `ws_client`
  - `agent_registry`
  - `target_type`
  - `target_id`
  - `message`
  - `intent`
  - `intent_router`
  - `butler_agent`
- Add:

```python
webhook_composer_agent=None
```

Store:

```python
self._webhook_composer_agent = webhook_composer_agent
```

Remove old `_targets`, `_agent_for_intent()`, `_resolve_intent()`, and `_scheduled_push()` after tests are migrated away from old WS mode.

Keep `WebhookSchedulerTarget`, `WebhookPushClient`, `load_webhook_targets()`, and `_scheduled_webhook_push()`.

- [ ] **Step 4: Update `_scheduled_webhook_push()`**

Replace agent selection logic with:

```python
if self._webhook_composer_agent is None:
    logger.error("Scheduler webhook: composer agent is None, cannot push")
    return

chat_id = target.chat_id or target.name
result = await self._webhook_composer_agent.handle(
    intent="webhook_compose",
    message=target.message,
    user_id=chat_id,
    db=db,
    extra_state={"chat_type": "group", "chat_id": chat_id},
)
```

Send `result.reply` with `self._webhook_client.send_markdown(...)`.

Remove `_build_webhook_butler_message()` because `WebhookComposerAgent` prompt now owns that behavior.

- [ ] **Step 5: Run scheduler tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_scheduler.py -q
```

Expected: PASS after old intent/WS scheduler tests are removed or rewritten.

- [ ] **Step 6: Commit**

```bash
git add src/scheduler/__init__.py tests/test_scheduler.py
git commit -m "feat: route webhook scheduler to composer agent"
```

---

### Task 9: Wire Main Application To Scene Agents

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_smoke.py`
- Modify: any main-import smoke tests that still expect debug route wiring

- [ ] **Step 1: Update smoke expectations**

In smoke tests, replace debug route expectations with callback route or app import expectations:

```python
def test_app_imports():
    """验证 FastAPI app 可以导入"""
    from src.main import app

    assert app.title == "Personal Butler Agent"
```

If a test inspects registered routes, assert `/api/debug/message` is absent:

```python
def test_debug_route_removed():
    """验证本地 debug 消息入口已删除"""
    from src.main import app

    paths = {route.path for route in app.routes}
    assert "/api/debug/message" not in paths
```

- [ ] **Step 2: Run smoke tests and verify they fail if main still imports deleted paths**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_smoke.py -q
```

Expected: FAIL until `src/main.py` is rewired and debug imports are removed.

- [ ] **Step 3: Update `src/main.py` imports and singletons**

Remove imports:

```python
from src.intent.router import IntentRouter
from src.agents.butler import ButlerAgent
from src.agents.registry import AgentRegistry
from src.router.debug import create_debug_router
```

Add imports:

```python
from src.agents.private_butler import PrivateButlerAgent
from src.agents.group_mention import GroupMentionAgent
from src.agents.webhook_composer import WebhookComposerAgent
```

Replace singletons:

```python
private_butler_agent = PrivateButlerAgent(
    llm_client=llm_client,
    fitness_agent=fitness_agent,
    meal_agent=meal_agent,
    summary_agent=summary_agent,
    knowledge_service=knowledge_service,
    web_search_service=web_search_service,
)
group_mention_agent = GroupMentionAgent(
    llm_client=llm_client,
    summary_agent=summary_agent,
)
webhook_composer_agent = WebhookComposerAgent(llm_client=llm_client)
```

Remove `intent_router`, `agent_registry`, `butler_agent`, and all registry registration.

- [ ] **Step 4: Update scheduler construction in `src/main.py`**

Replace scheduler construction with:

```python
scheduler_manager = SchedulerManager(
    db_session_factory=async_session,
    webhook_composer_agent=webhook_composer_agent,
    webhook_client=WebhookPushClient(),
    webhook_targets=targets,
)
```

- [ ] **Step 5: Remove debug router registration**

Delete:

```python
debug_router = create_debug_router(...)
app.include_router(debug_router)
```

Do not add a replacement debug/dev message API.

- [ ] **Step 6: Update callback router construction**

Use:

```python
create_aibot_callback_router(
    token=settings.wecom_aibot_token,
    encoding_aes_key=settings.wecom_aibot_encoding_aes_key,
    receive_id=settings.wecom_aibot_bot_id,
    private_agent=private_butler_agent,
    group_agent=group_mention_agent,
    db_session_factory=async_session,
)
```

- [ ] **Step 7: Run smoke and callback tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_smoke.py tests/test_aibot_callback.py tests/test_scheduler.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/main.py tests/test_smoke.py
git commit -m "feat: wire app to scene agents"
```

---

### Task 10: Remove Old Debug, Intent, WS, And Butler Code

**Files:**
- Delete: `src/agents/butler/`
- Delete: `src/intent/`
- Delete: `src/router/debug.py`
- Delete: `src/router/`
- Delete: `src/wechat/message_handler.py`
- Delete: `src/wechat/ws_client.py`
- Delete: `tests/test_api.py`
- Delete: `tests/test_intent.py`
- Delete: `tests/test_message_handler.py`
- Delete: `tests/test_ws_client.py`
- Modify: `src/wechat/__init__.py`
- Modify: `tests/__init__.py` only if it references removed modules

- [ ] **Step 1: Search for old references before deletion**

Run:

```bash
rg -n "src\\.agents\\.butler|agents\\.butler|IntentRouter|src\\.intent|create_debug_router|api/debug|handle_ws_message|WeComWSClient|ws_client|message_handler" src tests docs deployment-guide.en.md 部署指南.md
```

Expected: references remain in files scheduled for update or deletion.

- [ ] **Step 2: Delete old files**

Run:

```bash
rm -rf src/agents/butler
rm -rf src/intent
rm -rf src/router
rm -f src/wechat/message_handler.py
rm -f src/wechat/ws_client.py
rm -f tests/test_api.py
rm -f tests/test_intent.py
rm -f tests/test_message_handler.py
rm -f tests/test_ws_client.py
```

- [ ] **Step 3: Update `src/wechat/__init__.py`**

Ensure it only exports kept callback pieces:

```python
"""
企业微信智能机器人 URL 回调集成
保留 URL callback 入站、回调加解密、入站落库和 response_url 回复能力。
"""
from .callback_handler import ResponseUrlReplyClient, handle_callback_message
from .callback_router import create_aibot_callback_router

__all__ = [
    "ResponseUrlReplyClient",
    "create_aibot_callback_router",
    "handle_callback_message",
]
```

- [ ] **Step 4: Verify no old runtime references remain**

Run:

```bash
rg -n "src\\.agents\\.butler|agents\\.butler|IntentRouter|src\\.intent|create_debug_router|api/debug|handle_ws_message|WeComWSClient|ws_client|message_handler" src tests
```

Expected: no output.

- [ ] **Step 5: Run focused tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_messaging.py tests/test_group_mention_agent.py tests/test_webhook_composer_agent.py tests/test_aibot_callback.py tests/test_scheduler.py tests/test_smoke.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "refactor: remove old message entrypoints"
```

---

### Task 11: Update Documentation

**Files:**
- Modify: `deployment-guide.en.md`
- Modify: `部署指南.md`
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/decisions.md`
- Modify: `docs/agent/config-variables.md`
- Modify: `docs/agent/troubleshooting.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Search documentation for stale references**

Run:

```bash
rg -n "debug|/api/debug|WebSocket|WS|IntentRouter|src/intent|ButlerAgent|agents/butler|message_handler|ws_client" AGENTS.md CLAUDE.md deployment-guide.en.md 部署指南.md docs/agent
```

Expected: several stale references that need editing.

- [ ] **Step 2: Update deployment guides**

In `deployment-guide.en.md` and `部署指南.md`:

- Remove the debug endpoint curl section.
- State local testing uses the real WeChat Work URL callback through an HTTPS tunnel.
- Keep:

```bash
uv sync
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
DEEPSEEK_API_KEY=test uv run pytest -q
```

Add a short note:

```text
The app no longer exposes a local debug/dev message API. Configure the WeChat Work intelligent robot callback URL through HTTPS tunneling or production HTTPS.
```

- [ ] **Step 3: Update `docs/agent/active-context.md`**

Replace the current state summary with:

```markdown
The app exposes WeChat Work intelligent robot URL callback mode as the only inbound message API. Private chat messages enter `PrivateButlerAgent`; group callback messages are first persisted by `group_policy`, then allowed trigger messages enter `GroupMentionAgent`; scheduler webhook jobs use `WebhookComposerAgent` to generate markdown content before `WebhookPushClient` sends it.
```

Remove statements that say `POST /api/debug/message` is current or that default replyable messages enter old `ButlerAgent`.

- [ ] **Step 4: Update `docs/agent/patterns.md`**

Add sections:

```markdown
## Scene-First Dispatch

Runtime message routing starts with the communication scene, not a global intent classifier.

1. URL callback messages are normalized into `InboundMessage`.
2. `dispatch_message()` routes `single` chat to `PrivateButlerAgent`.
3. `dispatch_message()` sends `group` chat through `apply_group_policy()`.
4. Scheduler webhook jobs bypass chat dispatch and call `WebhookComposerAgent`.

## Group Policy

Group messages are saved before any reply decision. Non-trigger messages stop after persistence and cleanup. Allowed triggers enter `GroupMentionAgent`; training and meal requests are rejected in group context.
```

- [ ] **Step 5: Update `docs/agent/decisions.md`**

Append a new ADR:

```markdown
## ADR-016: Scene Agents Replace Global Intent And All-Purpose Butler

Private chat, group mention, and scheduled webhook push have different product boundaries. A single all-purpose ButlerAgent and global IntentRouter made these boundaries implicit and fragile.

Decision:
- Private chat uses `PrivateButlerAgent`.
- Group mention uses `GroupMentionAgent`.
- Scheduler webhook push uses `WebhookComposerAgent`.
- Debug/dev message API, WebSocket compatibility, global `src/intent/`, and old `src/agents/butler/` are removed.

Reasoning:
- Scene boundaries are easier to test and document.
- Group chat cannot accidentally access training or meal tools.
- Webhook composition is no longer treated like a user chat request.
- Real integration testing now uses WeChat Work URL callback through HTTPS tunneling.
```

- [ ] **Step 6: Update config and troubleshooting docs**

In `docs/agent/config-variables.md`:

- Keep DeepSeek, URL callback, scheduler target, web search config.
- Remove or rewrite any debug API and WS runtime guidance.

In `docs/agent/troubleshooting.md`:

- Remove WS-only troubleshooting sections or mark them as historical and not current runtime.
- Keep URL callback, `response_url`, scheduler webhook, and public 404 diagnostics.

- [ ] **Step 7: Update root agent docs only if needed**

If `AGENTS.md` still mentions debug or WS as current interfaces, update both `AGENTS.md` and `CLAUDE.md` with identical content. After editing, verify:

```bash
cmp -s AGENTS.md CLAUDE.md
```

Expected: exit code 0.

- [ ] **Step 8: Commit**

```bash
git add AGENTS.md CLAUDE.md deployment-guide.en.md 部署指南.md docs/agent
git commit -m "docs: document scene agent architecture"
```

---

### Task 12: Full Verification And Cleanup

**Files:**
- No planned source edits unless verification finds missed references.

- [ ] **Step 1: Run stale-reference scan**

Run:

```bash
rg -n "POST /api/debug/message|/api/debug/message|create_debug_router|src/router|IntentRouter|src/intent|handle_ws_message|WeComWSClient|src/agents/butler|ButlerAgent" .
```

Expected: no runtime references. Historical design documents under `docs/superpowers/` may still mention old architecture; do not edit historical specs/plans unless they are presented as current docs.

- [ ] **Step 2: Run full test suite**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: PASS.

- [ ] **Step 3: Import app and list routes**

Run:

```bash
DEEPSEEK_API_KEY=test uv run python - <<'PY'
from src.main import app
paths = sorted(getattr(route, "path", "") for route in app.routes)
print("\n".join(paths))
assert "/api/debug/message" not in paths
PY
```

Expected: output includes `/api/wechat/aibot/callback` only when callback config is provided at import time. It must not include `/api/debug/message`.

- [ ] **Step 4: Check changed files**

Run:

```bash
git status --short
```

Expected: only intentional final cleanup changes, or clean working tree if all tasks committed.

- [ ] **Step 5: Commit final cleanup if needed**

If verification required small cleanup edits:

```bash
git add -A
git commit -m "chore: finish scene agent refactor cleanup"
```

If no cleanup edits were needed, do not create an empty commit.
