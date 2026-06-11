# 群投票功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在企业微信群聊中通过智能机器人创建投票、成员投票、自动公布结果。

**Architecture:** 新增 PollAgent 领域 agent（StateGraph），修改 group_policy 识别投票触发词，修改 GroupMentionAgent 路由投票意图到 PollAgent，修改 SchedulerManager 支持动态一次性任务，新增 Poll/PollVote/GroupWebhook 三张 ORM 表。

**Tech Stack:** Python 3.13+, LangGraph, SQLAlchemy 2 async, APScheduler, 复用现有 LLMClient/WebhookPushClient

---

### Task 1: 创建 ORM 模型

**Files:**
- Create: `src/models/poll.py`
- Create: `src/models/group_webhook.py`
- Modify: `src/models/__init__.py`

- [ ] **Step 1: 创建 Poll 和 PollVote ORM 模型**

```python
"""
群投票 ORM 模型
存储群聊投票及其选项和成员投票记录。

Workflow:
1. PollAgent.create_poll_node 解析群聊 @bot 投票请求后写入 Poll
2. PollAgent.cast_vote_node 记录或更新 PollVote（一人一票 UPSERT）
3. PollAgent.view_results_node/end_poll_node 查询 PollVote 聚合统计并格式化展示
4. 到期时 SchedulerManager 回调查询结果并推送
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint

from src.db.base import Base


class Poll(Base):
    """群投票表"""

    __tablename__ = "polls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    chat_id = Column(String(256), nullable=False, index=True)
    """群聊 ID，对应企业微信回调 chatid"""

    creator_user_id = Column(String(256), nullable=False)
    """投票创建者 userid"""

    title = Column(String(512), nullable=False)
    """投票标题，例如“周末团建去哪？”"""

    options = Column(JSON, nullable=False)
    """选项列表，例如 ["香山", "故宫", "颐和园"]"""

    end_time = Column(DateTime, nullable=True)
    """到期时间，空表示手动结束"""

    status = Column(String(32), nullable=False, default="active")
    """状态：active / ended"""

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    """创建时间"""


class PollVote(Base):
    """投票记录表，一人一票"""

    __tablename__ = "poll_votes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    poll_id = Column(Integer, ForeignKey("polls.id"), nullable=False, index=True)
    """关联 Poll.id"""

    user_id = Column(String(256), nullable=False)
    """投票人 userid"""

    option_index = Column(Integer, nullable=False)
    """选项序号，0-based"""

    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    """最后投票或改票时间"""

    __table_args__ = (UniqueConstraint("poll_id", "user_id"),)
    """同一投票中每人只能投一次票，改票通过 UPSERT 覆盖"""
```

- [ ] **Step 2: 创建 GroupWebhook ORM 模型**

```python
"""
群 webhook 注册表 ORM 模型
存储群聊 chat_id 到企业微信群机器人 webhook URL 的映射。

Workflow:
1. 管理员通过私聊或直接写库注册群 webhook
2. PollAgent 到期推送时通过 chat_id 查找 webhook_url
3. 后续可替换或补充现有的 SCHEDULER_TARGETS_FILE 静态配置
"""
from sqlalchemy import Column, String

from src.db.base import Base


class GroupWebhook(Base):
    """群 webhook 注册表"""

    __tablename__ = "group_webhooks"

    chat_id = Column(String(256), primary_key=True)
    """群聊 ID，对应企业微信回调 chatid"""

    webhook_url = Column(String(1024), nullable=False)
    """企业微信群机器人 webhook 地址"""

    display_name = Column(String(256), nullable=True)
    """用户可见的群名称，用于展示"""
```

- [ ] **Step 3: 更新 models/__init__.py 导出**

```python
"""ORM 模型包，包含 SQLite 数据表映射"""
from src.models.group_message import GroupMessage
from src.models.conversation import ConversationMessage, ConversationSummary
from src.models.knowledge import (
    KnowledgeChunk,
    KnowledgeChunkEmbedding,
    KnowledgeDocument,
)
from src.models.inbound_message import InboundMessage
from src.models.poll import Poll, PollVote
from src.models.group_webhook import GroupWebhook
from src.models.reminder import Reminder, ReminderRun

__all__ = [
    "GroupMessage",
    "ConversationMessage",
    "ConversationSummary",
    "KnowledgeDocument",
    "KnowledgeChunk",
    "KnowledgeChunkEmbedding",
    "InboundMessage",
    "Poll",
    "PollVote",
    "GroupWebhook",
    "Reminder",
    "ReminderRun",
]
```

- [ ] **Step 4: 保存并提交**

```bash
git add src/models/poll.py src/models/group_webhook.py src/models/__init__.py
git commit -m "feat: add Poll, PollVote, and GroupWebhook ORM models"
```

---

### Task 2: 创建 PollAgent 状态定义

**Files:**
- Create: `src/agents/poll/__init__.py`
- Create: `src/agents/poll/state.py`

- [ ] **Step 1: 创建 __init__.py**

```python
"""PollAgent 包，负责群投票的创建、投票、查看和结束全生命周期"""
from src.agents.poll.graph import PollAgent

__all__ = ["PollAgent"]
```

- [ ] **Step 2: 创建 state.py**

```python
"""
PollAgent 状态定义
定义群投票创建、投票、查看和结束时在 StateGraph 中传递的字段。

Workflow:
  GroupMentionAgent → PollAgent.handle()
  → StateGraph 节点 → AgentResponse
"""
from typing import Any

from typing_extensions import TypedDict


class PollState(TypedDict, total=False):
    """投票 agent 状态字典"""

    intent: str
    """投票操作意图：create_poll / cast_vote / view_results / end_poll"""

    message: str
    """用户原始消息"""

    user_id: str
    """当前用户 ID"""

    chat_id: str | None
    """群聊 ID"""

    reply: str
    """最终返回给用户的自然语言回复"""

    data: dict[str, Any]
    """结构化结果数据，如投票统计"""
```

- [ ] **Step 3: 保存并提交**

```bash
git add src/agents/poll/__init__.py src/agents/poll/state.py
git commit -m "feat: add PollAgent state definition"
```

---

### Task 3: 创建 PollAgent 节点函数

**Files:**
- Create: `src/agents/poll/nodes.py`

- [ ] **Step 1: 创建完整节点文件**

```python
"""
PollAgent 节点函数
实现投票意图分类、创建投票、投票、查看结果和结束投票五个节点。

Workflow:
  classify_poll_intent 根据关键词或状态中的 category 分流
  → create_poll_node / cast_vote_node / view_results_node / end_poll_node
  → 返回 reply 和 data
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from langgraph.config import get_config
from sqlalchemy import func, select

from src.models.poll import Poll, PollVote
from src.models.group_webhook import GroupWebhook

# ── 常量 ──────────────────────────────────────────────

TIME_PARSE_PROMPT = """你是时间解析器。从用户消息中提取投票结束时间，只返回 ISO 8601 格式的 UTC 时间字符串，例如"2026-06-12T09:00:00Z"。

当前时间：{now}
默认时区：Asia/Shanghai

规则：
- "明天下午5点" → 明天的 17:00 CST → 明天的 09:00 UTC
- "一小时后" → 当前时间 + 1 小时
- "周五12点" → 本周五 12:00 CST
- 如果没有指定结束时间，返回空字符串""

只返回时间字符串或空字符串，不要输出其他内容。"""


# ── 选项解析 ───────────────────────────────────────────

def _parse_poll_options(message: str) -> list[str] | None:
    """从消息中解析投票选项

    参数:
        message: 用户原始消息

    返回:
        list[str] | None: 选项列表；解析失败返回 None
    """
    pattern = r"([A-Za-z])[.、．]\s*([^\s,，A-Za-z0-9]+(?:[^\s,，]*[^\s,，])?)"
    matches: list[tuple[str, str]] = re.findall(pattern, message)
    if len(matches) < 2:
        return None
    seen_letters: set[str] = set()
    options: list[str] = []
    for letter, label in matches:
        lower = letter.lower()
        if lower in seen_letters:
            continue
        seen_letters.add(lower)
        options.append(label.strip())
    if len(options) < 2:
        return None
    return options


def _extract_title(message: str) -> str:
    """从消息中提取投票标题

    参数:
        message: 用户原始消息

    返回:
        str: 投票标题
    """
    title = re.sub(r"[A-Za-z][.、．]\s*[^\s,，]+", "", message)
    title = re.sub(r"，?\s*(明天|今天|后天|周[一二三四五六日]|\d+点|\d+:\d+|一?小?时后|结束|截止).*$", "", title)
    for keyword in ("创建投票", "发起投票", "新建投票", "投票", "："):
        title = title.replace(keyword, "", 1)
    return title.strip().strip("：:").strip() or "投票"


# ── 投票选项字母识别 ────────────────────────────────────

def _parse_vote_option(message: str, option_count: int) -> int | None:
    """从短消息中提取投票选项序号

    参数:
        message: 用户消息
        option_count: 当前投票的选项总数

    返回:
        int | None: 选项序号（0-based）；无法识别返回 None
    """
    text = message.strip()
    m = re.match(r"投票\s*([A-Za-z])", text)
    if m:
        letter = m.group(1)
    else:
        m = re.match(r"选\s*([A-Za-z])", text)
        if m:
            letter = m.group(1)
        else:
            m = re.match(r"([A-Za-z])$", text)
            if m:
                letter = m.group(1)
            else:
                return None
    index = ord(letter.lower()) - ord("a")
    if 0 <= index < option_count:
        return index
    return None


# ── 时间解析 ───────────────────────────────────────────

async def _parse_end_time(message: str, llm) -> datetime | None:
    """调用 LLM 解析自然语言结束时间

    参数:
        message: 用户原始消息
        llm: LLMClient 实例

    返回:
        datetime | None: UTC 结束时间；解析失败返回 None
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = await llm.chat(
        messages=[
            {"role": "system", "content": TIME_PARSE_PROMPT.format(now=now)},
            {"role": "user", "content": message},
        ],
        temperature=0.1,
    )
    text = raw.strip().strip('"').strip("'")
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


# ── 格式化 ─────────────────────────────────────────────

def _format_poll_card(poll: Poll) -> str:
    """格式化投票卡片

    参数:
        poll: Poll ORM 对象

    返回:
        str: 投票展示文本
    """
    options = poll.options
    if isinstance(options, str):
        options = json.loads(options)
    labels = [f"{chr(65 + i)}. {opt}" for i, opt in enumerate(options)]
    lines = [f"📊 投票已创建「{poll.title}」", " | ".join(labels)]
    if poll.end_time:
        end_str = poll.end_time.strftime("%Y-%m-%d %H:%M")
        lines.append(f"⏰ 截止：{end_str}（UTC）")
    lines.append("回复 @bot + 选项字母即可投票")
    return "\n".join(lines)


def _format_results(poll: Poll, counts: dict[int, int]) -> str:
    """格式化投票结果

    参数:
        poll: Poll ORM 对象
        counts: {option_index: vote_count}

    返回:
        str: 结果展示文本
    """
    options = poll.options
    if isinstance(options, str):
        options = json.loads(options)
    total = sum(counts.values())
    max_votes = max(counts.values()) if counts else 0
    lines = []
    for i, opt in enumerate(options):
        cnt = counts.get(i, 0)
        marker = " 🏆" if cnt == max_votes and cnt > 0 else ""
        lines.append(f"{chr(65 + i)}.{opt} {cnt}票{marker}")
    status = "结束" if poll.status == "ended" else "当前"
    header = f"📊 {status}投票「{poll.title}」"
    return header + "\n" + " | ".join(lines) + f"\n共{total}人参与"


# ── 节点函数 ───────────────────────────────────────────

async def _get_active_poll(db, chat_id: str) -> Poll | None:
    """查询群内最近一个活跃投票

    参数:
        db: SQLAlchemy 异步会话
        chat_id: 群聊 ID

    返回:
        Poll | None: 最近创建的 active poll；无则 None
    """
    result = await db.execute(
        select(Poll)
        .where(Poll.chat_id == chat_id, Poll.status == "active")
        .order_by(Poll.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_active_polls(db, chat_id: str) -> list[Poll]:
    """查询群内所有活跃投票

    参数:
        db: SQLAlchemy 异步会话
        chat_id: 群聊 ID

    返回:
        list[Poll]: 活跃投票列表，按创建时间降序
    """
    result = await db.execute(
        select(Poll)
        .where(Poll.chat_id == chat_id, Poll.status == "active")
        .order_by(Poll.created_at.desc())
    )
    return list(result.scalars().all())


async def _count_votes(db, poll_id: int) -> dict[int, int]:
    """统计投票选项的票数

    参数:
        db: SQLAlchemy 异步会话
        poll_id: 投票 ID

    返回:
        dict[int, int]: {option_index: vote_count}
    """
    result = await db.execute(
        select(PollVote.option_index, func.count(PollVote.id))
        .where(PollVote.poll_id == poll_id)
        .group_by(PollVote.option_index)
    )
    return {row[0]: row[1] for row in result.all()}


async def classify_poll_intent(state: dict) -> dict:
    """分类投票意图

    参数:
        state: PollState

    返回:
        dict: 包含 intent 的状态更新
    """
    existing = state.get("intent", "")
    if existing in {"create_poll", "cast_vote", "view_results", "end_poll"}:
        return {"intent": existing}
    return {"intent": "view_results", "reply": "无法识别投票操作，请说明要创建投票、投票、查看结果还是结束投票。"}


async def create_poll_node(state: dict) -> dict:
    """创建群投票：解析选项和时间，写入 Poll 表，注册调度任务

    参数:
        state: PollState

    返回:
        dict: 包含 reply 的状态更新
    """
    config = get_config()["configurable"]
    db = config["db"]
    llm = config["llm"]
    scheduler_manager = config.get("scheduler_manager")
    message = state.get("message", "")
    user_id = state.get("user_id", "")
    chat_id = state.get("chat_id", "")

    options = _parse_poll_options(message)
    if options is None:
        return {"reply": "请使用格式创建投票：\n创建投票：标题？A.选项1 B.选项2 C.选项3\n\n至少需要2个选项。"}

    title = _extract_title(message)
    end_time = await _parse_end_time(message, llm)

    poll = Poll(
        chat_id=chat_id,
        creator_user_id=user_id,
        title=title,
        options=options,
        end_time=end_time,
        status="active",
    )
    db.add(poll)
    await db.flush()

    if end_time and scheduler_manager is not None:
        try:
            scheduler_manager.schedule_poll_end(poll.id, end_time)
        except Exception:
            pass

    return {"reply": _format_poll_card(poll), "data": {"poll_id": poll.id}}


async def cast_vote_node(state: dict) -> dict:
    """记录或更新投票

    参数:
        state: PollState

    返回:
        dict: 包含 reply 的状态更新
    """
    config = get_config()["configurable"]
    db = config["db"]
    message = state.get("message", "")
    user_id = state.get("user_id", "")
    chat_id = state.get("chat_id", "")

    active_polls = await _get_active_polls(db, chat_id)
    if not active_polls:
        return {"reply": "当前没有进行中的投票。"}

    poll = active_polls[0]

    if len(active_polls) > 1:
        sub = re.search(r"投票\s*(\d+)", message)
        if sub:
            idx = int(sub.group(1)) - 1
            if 0 <= idx < len(active_polls):
                poll = active_polls[idx]
            else:
                return {"reply": f"投票编号 {idx + 1} 不存在，当前有 {len(active_polls)} 个进行中的投票。"}
        else:
            m2 = re.search(r"给[「「\s]*([^」」\s]+)", message)
            if m2:
                keyword = m2.group(1)
                matched = [p for p in active_polls if keyword in p.title]
                if len(matched) == 1:
                    poll = matched[0]
                elif len(matched) > 1:
                    titles = "、".join(p.title for p in matched)
                    return {"reply": f"「{keyword}」匹配到多个投票：{titles}\n请用“@bot 投票1 A”指明。"}
                else:
                    titles = "、".join(p.title for p in active_polls)
                    return {"reply": f"当前有 {len(active_polls)} 个进行中的投票：{titles}\n请用“@bot 投票1 A”或“@bot 给「标题」投A”指明。"}
            else:
                titles = " | ".join(f"投票{i+1}「{p.title}」" for i, p in enumerate(active_polls))
                return {"reply": f"当前有 {len(active_polls)} 个进行中的投票：{titles}\n回复“@bot 投票1 A”或直接“@bot A”投给最近创建的投票。"}

    option_index = _parse_vote_option(message, len(poll.options))
    if option_index is None:
        return {
            "reply": f"无法识别你的投票选项。请回复“@bot A”或“@bot 选B”（可选：{', '.join(chr(65 + i) for i in range(len(poll.options)))}）"
        }

    existing_vote = await db.execute(
        select(PollVote).where(
            PollVote.poll_id == poll.id,
            PollVote.user_id == user_id,
        )
    )
    vote = existing_vote.scalar_one_or_none()

    if vote is not None:
        old_label = poll.options[vote.option_index]
        vote.option_index = option_index
        vote.updated_at = datetime.utcnow()
        new_label = poll.options[option_index]
        return {
            "reply": f"✅ 已改票：从「{old_label}」→「{new_label}」",
            "data": {"poll_id": poll.id, "option_index": option_index},
        }

    db.add(PollVote(
        poll_id=poll.id,
        user_id=user_id,
        option_index=option_index,
    ))
    label = poll.options[option_index]
    return {
        "reply": f"✅ 已记录：你投了「{label}」",
        "data": {"poll_id": poll.id, "option_index": option_index},
    }


async def view_results_node(state: dict) -> dict:
    """查看当前投票结果

    参数:
        state: PollState

    返回:
        dict: 包含 reply 的状态更新
    """
    config = get_config()["configurable"]
    db = config["db"]
    chat_id = state.get("chat_id", "")

    poll = await _get_active_poll(db, chat_id)
    if poll is None:
        return {"reply": "当前没有进行中的投票。"}

    counts = await _count_votes(db, poll.id)
    return {"reply": _format_results(poll, counts), "data": {"poll_id": poll.id, "counts": counts}}


async def end_poll_node(state: dict) -> dict:
    """结束投票：标记 ended，取消调度任务，推送结果

    参数:
        state: PollState

    返回:
        dict: 包含 reply 的状态更新
    """
    config = get_config()["configurable"]
    db = config["db"]
    chat_id = state.get("chat_id", "")
    scheduler_manager = config.get("scheduler_manager")
    webhook_client = config.get("webhook_client")

    poll = await _get_active_poll(db, chat_id)
    if poll is None:
        return {"reply": "当前没有进行中的投票。"}

    poll.status = "ended"
    await db.flush()

    if scheduler_manager is not None:
        scheduler_manager.cancel_poll_end(poll.id)

    counts = await _count_votes(db, poll.id)
    result_text = _format_results(poll, counts)

    webhook_pushed = False
    if webhook_client is not None:
        webhook = await db.execute(
            select(GroupWebhook).where(GroupWebhook.chat_id == chat_id)
        )
        wh = webhook.scalar_one_or_none()
        if wh is not None:
            await webhook_client.send_markdown(wh.webhook_url, result_text)
            webhook_pushed = True

    suffix = "" if webhook_pushed else "\n（未配置群 webhook，无法主动推送）"
    return {"reply": result_text + suffix, "data": {"poll_id": poll.id, "counts": counts}}
```

- [ ] **Step 2: 保存并提交**

```bash
git add src/agents/poll/nodes.py
git commit -m "feat: add PollAgent node functions"
```

---

### Task 4: 创建 PollAgent 图组装类

**Files:**
- Create: `src/agents/poll/graph.py`

- [ ] **Step 1: 创建 PollAgent 类**

```python
"""
PollAgent 图组装
构建群投票 StateGraph，负责创建、投票、查看和结束投票的全生命周期。

Workflow:
  START → classify_poll_intent
             ├─ create_poll   → create_poll_node   → END
             ├─ cast_vote     → cast_vote_node     → END
             ├─ view_results  → view_results_node  → END
             └─ end_poll      → end_poll_node      → END
"""
from langgraph.graph import END, START, StateGraph

from src.agents.poll.nodes import (
    cast_vote_node,
    classify_poll_intent,
    create_poll_node,
    end_poll_node,
    view_results_node,
)
from src.agents.poll.state import PollState
from src.graph.memory import checkpointer as _checkpointer
from src.schemas.response import AgentResponse


def _route_by_intent(state: dict) -> str:
    """根据意图选择下一个节点

    参数:
        state: 当前图状态

    返回:
        str: 下一个节点名
    """
    intent = state.get("intent", "")
    if intent in {"create_poll", "cast_vote", "view_results", "end_poll"}:
        return intent
    return "view_results"


class PollAgent:
    """群投票 agent，处理群聊 @ 机器人的投票相关请求"""

    def __init__(self, llm_client, scheduler_manager=None, webhook_client=None):
        """初始化 PollAgent 并编译 StateGraph

        参数:
            llm_client: LLMClient 实例
            scheduler_manager: SchedulerManager 实例，用于注册到期任务
            webhook_client: WebhookPushClient 实例，用于推送结果

        返回:
            None
        """
        self._llm = llm_client
        self._scheduler_manager = scheduler_manager
        self._webhook_client = webhook_client
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 PollAgent StateGraph

        参数:
            无

        返回:
            CompiledStateGraph: 编译后的 LangGraph 图
        """
        builder = StateGraph(PollState)
        builder.add_node("classify", classify_poll_intent)
        builder.add_node("create_poll", create_poll_node)
        builder.add_node("cast_vote", cast_vote_node)
        builder.add_node("view_results", view_results_node)
        builder.add_node("end_poll", end_poll_node)

        builder.add_edge(START, "classify")
        builder.add_conditional_edges(
            "classify",
            _route_by_intent,
            {
                "create_poll": "create_poll",
                "cast_vote": "cast_vote",
                "view_results": "view_results",
                "end_poll": "end_poll",
            },
        )
        builder.add_edge("create_poll", END)
        builder.add_edge("cast_vote", END)
        builder.add_edge("view_results", END)
        builder.add_edge("end_poll", END)

        return builder.compile(checkpointer=_checkpointer)

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理群投票相关请求

        参数:
            intent: 投票意图：create_poll / cast_vote / view_results / end_poll
            message: 用户原始消息
            user_id: 当前用户 ID
            db: SQLAlchemy 异步数据库会话
            extra_state: 额外上下文，需包含 chat_id

        返回:
            AgentResponse: 投票操作结果
        """
        extra_state = extra_state or {}
        initial_state = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "chat_id": extra_state.get("chat_id"),
        }
        config = {
            "configurable": {
                "db": db,
                "llm": self._llm,
                "scheduler_manager": self._scheduler_manager,
                "webhook_client": self._webhook_client,
                "thread_id": f"poll:{extra_state.get('chat_id') or user_id}",
            }
        }
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(
            reply=result.get("reply", "投票处理失败，请稍后再试。"),
            data=result.get("data"),
        )
```

- [ ] **Step 2: 保存并提交**

```bash
git add src/agents/poll/graph.py
git commit -m "feat: add PollAgent graph class"
```

---

### Task 5: 修改 group_policy.py 加入投票触发识别

**Files:**
- Modify: `src/messaging/group_policy.py`

- [ ] **Step 1: 新增投票关键词常量和分类逻辑**

在现有常量定义之后（约第23行后），新增投票关键词：

```python
SUMMARY_KEYWORDS = ("总结", "摘要", "概括", "汇总")
WEATHER_KEYWORDS = ("天气", "气温", "下雨", "降雨")
QUESTION_MARKERS = ("?", "？", "吗", "怎么", "如何", "为什么", "什么")
POLL_CREATE_KEYWORDS = ("创建投票", "发起投票", "新建投票")
POLL_VIEW_KEYWORDS = ("投票结果", "查看投票", "投票情况")
POLL_END_KEYWORDS = ("结束投票", "关闭投票", "停止投票")
```

- [ ] **Step 2: 修改 `classify_group_trigger` 函数**

在检查 `QUESTION_MARKERS` 之前（约第50行前），新增投票关键词检查。修改后的完整函数：

```python
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
        return "weather"
    if any(keyword in normalized for keyword in POLL_CREATE_KEYWORDS):
        return "poll_create"
    if any(keyword in normalized for keyword in POLL_END_KEYWORDS):
        return "poll_end"
    if any(keyword in normalized for keyword in POLL_VIEW_KEYWORDS):
        return "poll_view"
    if any(marker in normalized for marker in QUESTION_MARKERS):
        return "simple_qa"
    return None
```

注意：`poll_vote` 不在 `classify_group_trigger` 中处理，因为它需要 DB 查询判断群内是否有 active poll。该逻辑在下一步的 `apply_group_policy` 中处理。

- [ ] **Step 3: 修改 `apply_group_policy` 函数，新增 poll_vote 检测**

在现有的 `classify_group_trigger` 调用之后，如果未命中任何触发词，检查是否为投票动作：

```python
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
    if category is not None:
        return GroupPolicyDecision(True, "trigger", category)

    # 未命中触发词时，检查是否为投票动作
    content_stripped = message.content.strip()
    if 1 <= len(content_stripped) <= 10:
        vote_category = await _detect_vote_action(db, message.chat_id, content_stripped)
        if vote_category is not None:
            return GroupPolicyDecision(True, "trigger", vote_category)

    return GroupPolicyDecision(False, "non_trigger")
```

在文件顶部 import 区新增 `select` 导入，并在文件末尾（或 `classify_group_trigger` 之后）添加 `_detect_vote_action` 函数：

```python
from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.messaging.inbound import InboundMessage
from src.models.group_message import GroupMessage
from src.models.poll import Poll
```

在 `classify_group_trigger` 之后新增：

```python
async def _detect_vote_action(db: AsyncSession, chat_id: str, content: str) -> str | None:
    """检测是否为投票动作：群内有 active poll 且消息看起来像投票

    参数:
        db: 异步数据库会话
        chat_id: 群聊 ID
        content: 消息文本

    返回:
        str | None: "poll_vote" 或 None
    """
    import re

    normalized = content.strip()
    # 匹配: A, 选A, 投票A, 选 A
    if re.match(r"^(选\s*)?[A-Za-z]$", normalized) or re.match(r"^投票\s*[A-Za-z]$", normalized):
        result = await db.execute(
            select(Poll).where(
                Poll.chat_id == chat_id,
                Poll.status == "active",
            ).limit(1)
        )
        if result.scalar_one_or_none() is not None:
            return "poll_vote"
    return None
```

最终 `group_policy.py` 的 import 块变为：

```python
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.messaging.inbound import InboundMessage
from src.models.group_message import GroupMessage
from src.models.poll import Poll
```

- [ ] **Step 4: 保存并提交**

```bash
git add src/messaging/group_policy.py
git commit -m "feat: add poll trigger detection to group policy"
```

---

### Task 6: 修改 GroupMentionAgent 路由投票意图

**Files:**
- Modify: `src/agents/group_mention/classifier.py`
- Modify: `src/agents/group_mention/nodes.py`
- Modify: `src/agents/group_mention/state.py`
- Modify: `src/agents/group_mention/graph.py`

- [ ] **Step 0: 修改 classifier.py，ALLOWED_CATEGORIES 新增 poll 类别**

若不修改，`classify_node` 中的 `if existing_category in ALLOWED_CATEGORIES` 会返回 False，导致投票分类被 LLM 兜底误判为 `unsupported`。

```python
ALLOWED_CATEGORIES = {
    "summarize_group",
    "weather",
    "simple_qa",
    "unsupported",
    "poll_create",
    "poll_vote",
    "poll_view",
    "poll_end",
}
```

- [ ] **Step 1: 修改 GroupMentionState，新增 poll_agent 字段**

在 `state.py` 中新增字段：

```python
class GroupMentionState(TypedDict, total=False):
    """群聊 @ Agent 图状态"""

    intent: str
    message: str
    user_id: str
    chat_type: str
    chat_id: str | None
    category: str | None
    messages: Annotated[list[AnyMessage], add_messages]
    reply: str
    data: dict | None
    error: str | None
    llm: object
    summary_agent: object
    weather_service: object
    poll_agent: object  # 新增
    db: object
```

- [ ] **Step 2: 修改 route_by_category，新增 poll 分支**

在 `nodes.py` 的 `route_by_category` 函数中新增 poll 路由：

```python
def route_by_category(state: dict) -> str:
    """根据分类结果选择下一个节点

    参数:
        state: 当前图状态

    返回:
        str: 下一个节点名
    """
    category = state.get("category", "unsupported")
    if category in {"summarize_group", "weather", "simple_qa"}:
        return category
    if category in {"poll_create", "poll_vote", "poll_view", "poll_end"}:
        return "poll"
    return "unsupported"
```

- [ ] **Step 3: 在 nodes.py 中新增 poll_node 函数**

```python
async def poll_node(state: dict) -> dict:
    """将投票请求委派给 PollAgent 处理

    参数:
        state: 当前图状态

    返回:
        dict: 回复和数据
    """
    poll_agent = state.get("poll_agent")
    if poll_agent is None:
        return {"reply": "投票功能暂不可用。"}

    category = state.get("category", "")
    intent_map = {
        "poll_create": "create_poll",
        "poll_vote": "cast_vote",
        "poll_view": "view_results",
        "poll_end": "end_poll",
    }
    intent = intent_map.get(category, "view_results")

    result = await poll_agent.handle(
        intent=intent,
        message=state.get("message", ""),
        user_id=state.get("user_id", ""),
        db=state["db"],
        extra_state={
            "chat_type": state.get("chat_type", "group"),
            "chat_id": state.get("chat_id"),
        },
    )
    return {"reply": result.reply, "data": result.data}
```

- [ ] **Step 4: 修改 GroupMentionAgent._build_graph，注册 poll_node**

在 `graph.py` 中：

导入 `poll_node`：

```python
from src.agents.group_mention.nodes import (
    build_initial_messages,
    call_model_with_tools,
    classify_node,
    extract_tool_reply,
    poll_node,
    route_by_category,
    simple_qa_node,
    summarize_group_node,
    unsupported_node,
    weather_unavailable_node,
)
```

在 `_build_graph` 方法中新增 poll 节点和路由：

```python
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
    builder.add_node("weather_unavailable", weather_unavailable_node)
    builder.add_node("simple_qa", simple_qa_node)
    builder.add_node("unsupported", unsupported_node)
    builder.add_node("poll", poll_node)  # 新增
    if self._tools:
        builder.add_node("agent", call_model_with_tools)
        builder.add_node("tools", ToolNode(self._tools))
        builder.add_node("extract_tool_reply", extract_tool_reply)

    builder.add_edge(START, "classify")
    weather_route = "agent" if self._tools else "weather_unavailable"
    builder.add_conditional_edges(
        "classify",
        route_by_category,
        {
            "summarize_group": "summarize_group",
            "weather": weather_route,
            "simple_qa": "simple_qa",
            "poll": "poll",  # 新增
            "unsupported": "unsupported",
        },
    )
    builder.add_edge("summarize_group", END)
    builder.add_edge("weather_unavailable", END)
    builder.add_edge("simple_qa", END)
    builder.add_edge("poll", END)  # 新增
    builder.add_edge("unsupported", END)
    if self._tools:
        builder.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "tools", END: "extract_tool_reply"},
        )
        builder.add_edge("tools", "agent")
        builder.add_edge("extract_tool_reply", END)
    return builder.compile()
```

- [ ] **Step 5: 修改 GroupMentionAgent.__init__，接收 poll_agent**

```python
class GroupMentionAgent:
    """群聊 @ 机器人场景 agent"""

    def __init__(self, llm_client, summary_agent, weather_service=None, poll_agent=None):
        """初始化群聊 @ agent

        参数:
            llm_client: LLM 客户端
            summary_agent: 群聊总结领域 agent
            weather_service: 天气服务；未注入时天气工具返回降级提示
            poll_agent: 群投票领域 agent；未注入时投票功能不可用

        返回:
            None
        """
        self._llm = llm_client
        self._summary_agent = summary_agent
        self._weather_service = weather_service
        self._poll_agent = poll_agent
        self._tools = [query_weather] if weather_service is not None else []
        self._graph = self._build_graph()
```

- [ ] **Step 6: 修改 handle() 方法，传递 poll_agent**

```python
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
        "category": extra_state.get("group_category"),
        "messages": build_initial_messages(message),
        "llm": self._llm,
        "summary_agent": self._summary_agent,
        "weather_service": self._weather_service,
        "poll_agent": self._poll_agent,  # 新增
        "db": db,
    }
    ...
```

- [ ] **Step 7: 保存并提交**

```bash
git add src/agents/group_mention/nodes.py src/agents/group_mention/state.py src/agents/group_mention/graph.py
git commit -m "feat: add poll routing to GroupMentionAgent"
```

---

### Task 7: 修改 SchedulerManager 支持动态一次性任务

**Files:**
- Modify: `src/scheduler/manager.py`

- [ ] **Step 1: 新增 schedule_poll_end 和 cancel_poll_end 方法**

在 `SchedulerManager` 类的末尾（在 `_process_due_reminders` 方法之后），新增两个公开方法和一个内部回调：

```python
def schedule_poll_end(self, poll_id: int, end_time):
    """注册投票到期一次性任务

    参数:
        poll_id: Poll.id
        end_time: 到期时间 datetime 对象

    返回:
        None
    """
    from datetime import datetime, timezone

    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    self._scheduler.add_job(
        self._push_poll_result,
        trigger="date",
        run_date=end_time,
        id=f"poll_end:{poll_id}",
        name=f"投票到期推送: poll_id={poll_id}",
        replace_existing=True,
        args=[poll_id],
    )
    logger.info("Poll scheduler: registered end job poll_id=%s at %s", poll_id, end_time)


def cancel_poll_end(self, poll_id: int):
    """取消投票到期任务

    参数:
        poll_id: Poll.id

    返回:
        None
    """
    job_id = f"poll_end:{poll_id}"
    try:
        self._scheduler.remove_job(job_id)
        logger.info("Poll scheduler: cancelled end job poll_id=%s", poll_id)
    except Exception:
        pass


async def _push_poll_result(self, poll_id: int):
    """投票到期回调：统计结果、推送 webhook、标记结束

    参数:
        poll_id: Poll.id

    返回:
        None
    """
    if self._webhook_client is None:
        logger.error("Poll scheduler: webhook_client is None, cannot push poll_id=%s", poll_id)
        return
    if self._db_session_factory is None:
        logger.error("Poll scheduler: db_session_factory is None, cannot push poll_id=%s", poll_id)
        return

    from sqlalchemy import func, select

    from src.models.poll import Poll, PollVote
    from src.models.group_webhook import GroupWebhook

    async with self._db_session_factory() as db:
        try:
            poll_result = await db.execute(select(Poll).where(Poll.id == poll_id))
            poll = poll_result.scalar_one_or_none()
            if poll is None:
                logger.warning("Poll scheduler: poll_id=%s not found", poll_id)
                return
            if poll.status != "active":
                logger.info("Poll scheduler: poll_id=%s already ended", poll_id)
                return

            poll.status = "ended"

            count_result = await db.execute(
                select(PollVote.option_index, func.count(PollVote.id))
                .where(PollVote.poll_id == poll_id)
                .group_by(PollVote.option_index)
            )
            counts = {row[0]: row[1] for row in count_result.all()}

            import json
            options = poll.options
            if isinstance(options, str):
                options = json.loads(options)
            total = sum(counts.values())
            max_votes = max(counts.values()) if counts else 0
            lines = []
            for i, opt in enumerate(options):
                cnt = counts.get(i, 0)
                marker = " 🏆" if cnt == max_votes and cnt > 0 else ""
                lines.append(f"{chr(65 + i)}.{opt} {cnt}票{marker}")
            result_text = f"📊 投票结束「{poll.title}」\n" + " | ".join(lines) + f"\n共{total}人参与"

            webhook_result = await db.execute(
                select(GroupWebhook).where(GroupWebhook.chat_id == poll.chat_id)
            )
            wh = webhook_result.scalar_one_or_none()
            if wh is not None:
                ok = await self._webhook_client.send_markdown(wh.webhook_url, result_text)
                if ok:
                    logger.info("Poll scheduler: pushed result poll_id=%s to chat_id=%s", poll_id, poll.chat_id)
                else:
                    logger.error("Poll scheduler: push failed poll_id=%s", poll_id)
            else:
                logger.info("Poll scheduler: no webhook for chat_id=%s, poll_id=%s ended silently", poll.chat_id, poll_id)

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Poll scheduler: error pushing poll_id=%s", poll_id)
```

- [ ] **Step 2: 保存并提交**

```bash
git add src/scheduler/manager.py
git commit -m "feat: add dynamic poll end scheduling to SchedulerManager"
```

---

### Task 8: 在 main.py 中注册 PollAgent

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: 导入 PollAgent**

```python
from src.agents.poll import PollAgent
```

- [ ] **Step 2: 模块级别创建 PollAgent（scheduler_manager 先传 None）**

关键时序约束：`group_mention_agent` 在模块级别用于路由注册，而 `scheduler_manager` 在 `lifespan` 中才创建。因此 PollAgent 必须分两步初始化。

**2a. 导入 PollAgent：**

在现有 import 区新增：

```python
from src.agents.poll import PollAgent
```

**2b. 删除原有的 `group_mention_agent` 创建（约第55-59行），替换为：**

```python
# 模块级别：先创建 PollAgent（scheduler 尚未就绪，传 None）
poll_agent = PollAgent(
    llm_client=llm_client,
    scheduler_manager=None,
    webhook_client=None,
)
group_mention_agent = GroupMentionAgent(
    llm_client=llm_client,
    summary_agent=summary_agent,
    weather_service=weather_service,
    poll_agent=poll_agent,
)
```

**2c. 在 lifespan 中，scheduler_manager 创建后注入到 poll_agent：**

在 `lifespan` 函数内，`scheduler_manager.start()` 之后新增：

```python
# scheduler_manager 就绪后，注入到 PollAgent
poll_agent._scheduler_manager = scheduler_manager
poll_agent._webhook_client = WebhookPushClient()
```

- [ ] **Step 3: 保存并提交**

```bash
git add src/main.py
git commit -m "feat: wire PollAgent into main app"
```

---

### Task 9: 集成验证

**Files:**
- 无新文件

- [ ] **Step 1: 验证所有模块可导入**

```bash
cd /Users/assle/dev/personal_butler_agent
uv run python -c "
from src.models.poll import Poll, PollVote
from src.models.group_webhook import GroupWebhook
from src.agents.poll import PollAgent
from src.messaging.group_policy import classify_group_trigger
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 2: 验证投票选项解析**

```bash
uv run python -c "
from src.agents.poll.nodes import _parse_poll_options, _extract_title
msg = '创建投票：周末团建去哪？A.香山 B.故宫 C.颐和园，明天下午5点结束'
opts = _parse_poll_options(msg)
title = _extract_title(msg)
assert opts == ['香山', '故宫', '颐和园'], f'Expected 3 options, got {opts}'
assert title == '周末团建去哪？', f'Expected title, got {title}'
print(f'Parse OK: title={title}, options={opts}')
"
```

Expected: `Parse OK: title=周末团建去哪？, options=['香山', '故宫', '颐和园']`

- [ ] **Step 3: 验证投票字母解析**

```bash
uv run python -c "
from src.agents.poll.nodes import _parse_vote_option
assert _parse_vote_option('A', 4) == 0
assert _parse_vote_option('选B', 4) == 1
assert _parse_vote_option('投票 C', 4) == 2
assert _parse_vote_option('hello', 4) is None
print('Vote parse OK')
"
```

Expected: `Vote parse OK`

- [ ] **Step 4: 验证 group_policy 投票触发词**

```bash
uv run python -c "
from src.messaging.group_policy import classify_group_trigger
assert classify_group_trigger('创建投票：测试？A.是 B.否') == 'poll_create'
assert classify_group_trigger('查看投票结果') == 'poll_view'
assert classify_group_trigger('结束投票') == 'poll_end'
print('Trigger classification OK')
"
```

Expected: `Trigger classification OK`

- [ ] **Step 5: 验证数据库建表**

```bash
uv run python -c "
from src.db.base import Base
from src.db.session import engine, async_session
import asyncio

async def verify():
    from src.models.poll import Poll, PollVote
    from src.models.group_webhook import GroupWebhook
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        from sqlalchemy import text
        for table in ['polls', 'poll_votes', 'group_webhooks']:
            result = await db.execute(text(f\"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'\"))
            assert result.scalar_one_or_none() is not None, f'Table {table} not found'
    print('All tables created OK')

asyncio.run(verify())
"
```

Expected: `All tables created OK`

- [ ] **Step 6: 运行现有测试确保无回归**

```bash
uv run pytest tests/ -x -q
```

Expected: 全部通过（无失败）

- [ ] **Step 7: 提交验证结果**

```bash
git add -A
git commit -m "chore: verify poll feature integration"
```
