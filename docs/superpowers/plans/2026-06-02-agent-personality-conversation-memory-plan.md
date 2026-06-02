# Agent Personality & Conversation Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add conversation context memory (6-turn recent messages + LLM-compressed summary in SQLite) to QA/Fitness(today_plan)/Meal agents, and rewrite all 4 agent system prompts with distinct personalities.

**Architecture:** New `ConversationMemory` module manages two SQLite tables. Three agent `handle()` methods inject memory before graph invocation and save exchanges after. Three state TypedDicts gain `conversation_summary` + `recent_messages` fields. Each agent's generate node splices context into LLM messages. System prompts are replaced inline in each agent's nodes.py.

**Tech Stack:** Python 3.13+, SQLAlchemy 2 async, pytest + pytest-asyncio, LangGraph

---

### Task 1: ORM models for conversation persistence

**Files:**
- Create: `src/models/conversation.py`
- Create: `tests/test_conversation_model.py`

- [ ] **Step 1: Write test file**

Create `tests/test_conversation_model.py`:

```python
"""
测试对话记忆 ORM 模型（conversation_messages + conversation_summaries）
"""
import pytest
from sqlalchemy import select, func

from src.models.conversation import ConversationMessage, ConversationSummary


async def test_save_and_retrieve_messages(db_session):
    """测试写入和读取对话消息，按时间升序排列"""
    msg1 = ConversationMessage(
        user_id="user_001", role="user", content="今天练胸",
        created_at="2026-06-02T10:00:00",
    )
    msg2 = ConversationMessage(
        user_id="user_001", role="assistant", content="好的，记录下来了！",
        created_at="2026-06-02T10:00:01",
    )
    db_session.add_all([msg1, msg2])
    await db_session.flush()

    result = await db_session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.user_id == "user_001")
        .order_by(ConversationMessage.created_at.asc())
    )
    messages = result.scalars().all()

    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "今天练胸"
    assert messages[1].role == "assistant"
    assert messages[1].content == "好的，记录下来了！"


async def test_get_recent_messages_by_user(db_session):
    """测试获取用户最近 N 条消息"""
    for i in range(20):
        db_session.add(ConversationMessage(
            user_id="user_multi",
            role="user" if i % 2 == 0 else "assistant",
            content=f"消息{i}",
            created_at=f"2026-06-02T10:{i:02d}:00",
        ))
    await db_session.flush()

    result = await db_session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.user_id == "user_multi")
        .order_by(ConversationMessage.created_at.desc())
        .limit(12)
    )
    recent = list(reversed(result.scalars().all()))

    assert len(recent) == 12
    assert recent[0].content == "消息8"
    assert recent[-1].content == "消息19"


async def test_delete_old_messages_by_user(db_session):
    """测试删除用户最早的 N 条消息"""
    for i in range(10):
        db_session.add(ConversationMessage(
            user_id="user_del",
            role="user" if i % 2 == 0 else "assistant",
            content=f"旧消息{i}",
            created_at=f"2026-06-02T10:{i:02d}:00",
        ))
    await db_session.flush()

    from sqlalchemy import delete
    subq = (
        select(ConversationMessage.id)
        .where(ConversationMessage.user_id == "user_del")
        .order_by(ConversationMessage.created_at.asc())
        .limit(6)
    )
    await db_session.execute(
        delete(ConversationMessage).where(ConversationMessage.id.in_(subq))
    )
    await db_session.flush()

    count_result = await db_session.execute(
        select(func.count()).select_from(ConversationMessage)
        .where(ConversationMessage.user_id == "user_del")
    )
    assert count_result.scalar() == 4


async def test_conversation_summary_upsert(db_session):
    """测试对话摘要的写入和更新"""
    summary = ConversationSummary(
        user_id="user_summ",
        summary_text="用户偏好练胸和背，目标是增肌",
        last_summarized_at="2026-06-02T12:00:00",
    )
    db_session.add(summary)
    await db_session.flush()

    result = await db_session.execute(
        select(ConversationSummary).where(ConversationSummary.user_id == "user_summ")
    )
    found = result.scalar_one()
    assert found.summary_text == "用户偏好练胸和背，目标是增肌"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_conversation_model.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'src.models.conversation'`

- [ ] **Step 3: Create the ORM model file**

Create `src/models/conversation.py`:

```python
"""
对话记忆持久化模型
存储用户对话消息和压缩摘要，支持最近消息查询和自动清理旧数据

在总流程中的位置:
  ConversationMemory → ConversationMessage.save / get_recent
  压缩触发时 → ConversationSummary upsert + 旧消息删除
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from src.db.base import Base


class ConversationMessage(Base):
    """对话消息模型，按 user_id 分组，压缩后自动清理旧消息"""

    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    user_id = Column(String(256), nullable=False, index=True)
    """用户标识"""

    role = Column(String(16), nullable=False)
    """消息角色：user 或 assistant"""

    content = Column(Text, nullable=False)
    """消息文本内容"""

    created_at = Column(String(32), nullable=False)
    """消息创建时间，ISO 格式"""


class ConversationSummary(Base):
    """对话摘要模型，每个用户一行，存储早期对话的压缩摘要"""

    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    user_id = Column(String(256), nullable=False, unique=True)
    """用户标识，每个用户唯一"""

    summary_text = Column(Text, nullable=False)
    """压缩后的对话摘要文本"""

    last_summarized_at = Column(String(32), nullable=False)
    """最后一次触发压缩的时间，ISO 格式"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_conversation_model.py -v`

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/models/conversation.py tests/test_conversation_model.py
git commit -m "feat: add conversation message and summary ORM models"
```

---

### Task 2: ConversationMemory module

**Files:**
- Create: `src/memory/__init__.py`
- Create: `src/memory/conversation.py`
- Create: `tests/test_conversation_memory.py`

- [ ] **Step 1: Write test file**

Create `tests/test_conversation_memory.py`:

```python
"""
测试 ConversationMemory 模块（get_context + save_exchange + 压缩触发）
"""
import pytest
from unittest.mock import AsyncMock

from src.memory.conversation import ConversationMemory
from src.models.conversation import ConversationMessage, ConversationSummary


async def test_get_context_empty(db_session):
    """测试空表的 get_context：返回空摘要和空消息列表"""
    mock_llm = AsyncMock()
    memory = ConversationMemory(mock_llm)
    summary, recent = await memory.get_context("user_none", db_session)

    assert summary is None
    assert recent == []


async def test_get_context_with_messages(db_session):
    """测试有消息时的 get_context：返回摘要和最近12条消息"""
    mock_llm = AsyncMock()
    from src.models.conversation import ConversationSummary

    db_session.add(ConversationSummary(
        user_id="user_with_data",
        summary_text="用户喜欢练腿",
        last_summarized_at="2026-06-02T10:00:00",
    ))
    for i in range(15):
        db_session.add(ConversationMessage(
            user_id="user_with_data",
            role="user" if i % 2 == 0 else "assistant",
            content=f"消息{i}",
            created_at=f"2026-06-02T10:{i:02d}:00",
        ))
    await db_session.flush()

    memory = ConversationMemory(mock_llm)
    summary, recent = await memory.get_context("user_with_data", db_session)

    assert summary == "用户喜欢练腿"
    assert len(recent) == 12
    assert recent[0]["role"] == "user"
    assert recent[0]["content"] == "消息4"


async def test_save_exchange(db_session):
    """测试 save_exchange：写入两条消息"""
    mock_llm = AsyncMock()
    memory = ConversationMemory(mock_llm)

    await memory.save_exchange("user_save", "今天练背", "好的！", db_session)

    from sqlalchemy import select
    result = await db_session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.user_id == "user_save")
        .order_by(ConversationMessage.created_at.asc())
    )
    messages = result.scalars().all()

    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "今天练背"
    assert messages[1].role == "assistant"
    assert messages[1].content == "好的！"


async def test_save_exchange_triggers_compression(db_session):
    """测试消息超过24条时触发压缩，LLM 被调用"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = "压缩后的对话摘要：用户定期训练，偏好胸背腿轮换"

    for i in range(24):
        db_session.add(ConversationMessage(
            user_id="user_compress",
            role="user" if i % 2 == 0 else "assistant",
            content=f"消息{i}",
            created_at=f"2026-06-02T10:{i:02d}:00",
        ))
    await db_session.flush()

    memory = ConversationMemory(mock_llm)
    await memory.save_exchange("user_compress", "今天练腿", "安排！", db_session)

    mock_llm.chat.assert_called_once()

    from sqlalchemy import select, func
    count_result = await db_session.execute(
        select(func.count()).select_from(ConversationMessage)
        .where(ConversationMessage.user_id == "user_compress")
    )
    assert count_result.scalar() <= 14

    summary_result = await db_session.execute(
        select(ConversationSummary).where(ConversationSummary.user_id == "user_compress")
    )
    summary = summary_result.scalar_one()
    assert "压缩后的对话摘要" in summary.summary_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_conversation_memory.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'src.memory.conversation'`

- [ ] **Step 3: Create the module**

Create `src/memory/__init__.py`:

```python
"""
对话记忆模块
提供 ConversationMemory 类，管理用户对话历史和摘要压缩
"""
from .conversation import ConversationMemory

__all__ = ["ConversationMemory"]
```

Create `src/memory/conversation.py`:

```python
"""
对话记忆管理
提供对话上下文获取、交换保存和自动压缩功能

在总流程中的位置:
  agent.handle() → ConversationMemory.get_context(user_id, db)
  → graph.ainvoke() → ConversationMemory.save_exchange(user_id, user_msg, reply, db)
  → _maybe_compress() 自动触发旧消息压缩

Workflow:
  1. get_context: 从 summaries 表取摘要 + 从 messages 表取最近12条
  2. save_exchange: 写入两条消息，超过24条时触发压缩
  3. _compress: 取最早12条 + 现有摘要 → LLM 生成新摘要 → upsert summaries + 删除旧消息
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, select

from src.models.conversation import ConversationMessage, ConversationSummary

logger = logging.getLogger(__name__)

MAX_MESSAGES = 24
WINDOW_SIZE = 12
COMPRESS_BATCH = 12

COMPRESS_PROMPT = """你是对话摘要器。把以下对话历史和之前的摘要压缩成一句简短摘要（不超过80字），
保留关键事实和偏好信息。

之前的摘要：{existing_summary}

最新对话：
{old_messages}

只输出摘要文本，不要多余的话。"""


class ConversationMemory:
    """对话记忆管理器，负责读写对话历史和自动压缩"""

    def __init__(self, llm_client):
        """初始化对话记忆管理器

        参数:
            llm_client: LLMClient 实例，用于生成摘要
        """
        self._llm = llm_client

    async def get_context(self, user_id: str, db) -> tuple[str | None, list[dict]]:
        """获取用户对话上下文（摘要 + 最近消息）

        参数:
            user_id: 用户标识
            db: SQLAlchemy 异步会话

        返回:
            tuple[str|None, list[dict]]: (摘要文本或None, 最近消息列表)
        """
        try:
            summary_result = await db.execute(
                select(ConversationSummary).where(
                    ConversationSummary.user_id == user_id
                )
            )
            summary_row = summary_result.scalar_one_or_none()
            summary = summary_row.summary_text if summary_row else None

            messages_result = await db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.user_id == user_id)
                .order_by(ConversationMessage.created_at.desc())
                .limit(WINDOW_SIZE)
            )
            recent = list(reversed(messages_result.scalars().all()))

            recent_dicts = [
                {"role": msg.role, "content": msg.content}
                for msg in recent
            ]
            return summary, recent_dicts
        except Exception:
            logger.exception("ConversationMemory.get_context failed for user=%s", user_id)
            return None, []

    async def save_exchange(
        self, user_id: str, user_msg: str, assistant_msg: str, db
    ) -> None:
        """保存一轮对话交换（用户消息 + 助手回复）

        参数:
            user_id: 用户标识
            user_msg: 用户消息文本
            assistant_msg: 助手回复文本
            db: SQLAlchemy 异步会话
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            db.add(ConversationMessage(
                user_id=user_id, role="user",
                content=user_msg, created_at=now,
            ))
            db.add(ConversationMessage(
                user_id=user_id, role="assistant",
                content=assistant_msg, created_at=now,
            ))
            await db.flush()

            await self._maybe_compress(user_id, db)
        except Exception:
            logger.exception("ConversationMemory.save_exchange failed for user=%s", user_id)

    async def _maybe_compress(self, user_id: str, db) -> None:
        """检查消息数是否需要压缩，超过阈值时触发

        参数:
            user_id: 用户标识
            db: SQLAlchemy 异步会话
        """
        try:
            count_result = await db.execute(
                select(func.count())
                .select_from(ConversationMessage)
                .where(ConversationMessage.user_id == user_id)
            )
            total = count_result.scalar()
            if total <= MAX_MESSAGES:
                return

            old_result = await db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.user_id == user_id)
                .order_by(ConversationMessage.created_at.asc())
                .limit(COMPRESS_BATCH)
            )
            old_messages = old_result.scalars().all()
            if not old_messages:
                return

            old_text = "\n".join(
                f"[{m.role}]: {m.content}" for m in old_messages
            )

            summary_result = await db.execute(
                select(ConversationSummary).where(
                    ConversationSummary.user_id == user_id
                )
            )
            summary_row = summary_result.scalar_one_or_none()
            existing = summary_row.summary_text if summary_row else "（无之前的摘要）"

            prompt = COMPRESS_PROMPT.format(
                existing_summary=existing,
                old_messages=old_text,
            )
            new_summary = await self._llm.chat(
                messages=[
                    {"role": "system", "content": "你是对话摘要器，输出简洁准确。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            new_summary = new_summary.strip()

            if not new_summary:
                return

            now = datetime.now(timezone.utc).isoformat()
            if summary_row:
                summary_row.summary_text = new_summary
                summary_row.last_summarized_at = now
            else:
                db.add(ConversationSummary(
                    user_id=user_id,
                    summary_text=new_summary,
                    last_summarized_at=now,
                ))
            await db.flush()

            old_ids = [m.id for m in old_messages]
            await db.execute(
                delete(ConversationMessage).where(
                    ConversationMessage.id.in_(old_ids)
                )
            )
            await db.flush()
        except Exception:
            logger.exception("ConversationMemory._compress failed for user=%s", user_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_conversation_memory.py -v`

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/memory/__init__.py src/memory/conversation.py tests/test_conversation_memory.py
git commit -m "feat: add ConversationMemory module with context retrieval and compression"
```

---

### Task 3: Agent state TypedDict updates

**Files:**
- Modify: `src/agents/qa/state.py`
- Modify: `src/agents/fitness/state.py`
- Modify: `src/agents/meal/state.py`

- [ ] **Step 1: Add new fields to state files**

Add to `src/agents/qa/state.py` — `QAState` TypedDict, after the `error` field (before the closing `}`) :

```python
    conversation_summary: Optional[str]
    """早期对话的压缩摘要文本"""

    recent_messages: list[dict]
    """最近6轮对话消息列表，每条为 {"role": "user"|"assistant", "content": "..."}"""
```

Add to `src/agents/fitness/state.py` — `FitnessState` TypedDict, after `error`:

```python
    conversation_summary: Optional[str]
    """早期对话的压缩摘要文本"""

    recent_messages: list[dict]
    """最近6轮对话消息列表"""
```

Add to `src/agents/meal/state.py` — `MealState` TypedDict, after `error`:

```python
    conversation_summary: Optional[str]
    """早期对话的压缩摘要文本"""

    recent_messages: list[dict]
    """最近6轮对话消息列表"""
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `uv run pytest tests/test_fitness.py tests/test_qa.py tests/test_meal.py -v`

Expected: all PASS (TypedDict total=False allows extra fields, no breakage)

- [ ] **Step 3: Commit**

```bash
git add src/agents/qa/state.py src/agents/fitness/state.py src/agents/meal/state.py
git commit -m "feat: add conversation_summary and recent_messages to agent state types"
```

---

### Task 4: QA Agent — new prompt + memory injection

**Files:**
- Modify: `src/agents/qa/nodes.py:14-19, 44-67`
- Modify: `src/agents/qa/graph.py:51-66`

- [ ] **Step 1: Update QA system prompt**

In `src/agents/qa/nodes.py`, replace `QA_SYSTEM_PROMPT`:

```python
QA_SYSTEM_PROMPT = """你是"小管家"，用户的私人 AI 助理，陪伴用户日常生活。

性格底色：细心、温暖、偶尔带点小幽默但不油腻。

说话方式：
- 像认识很久的朋友，自然口语化，不要客服腔和机器人感
- 用户偏好中有名字的话，偶尔叫名字显得亲近
- 关心用户的感受和状态，不只是一问一答
- 适当用 emoji 传递情绪，不泛滥
- 不知道就说不知道，不要编

回复长度：日常聊天 2-4 句即可，深入问题可以详细展开。

用户档案（来自系统记录）：
{preferences}

{conversation_context}"""
```

- [ ] **Step 2: Update generate_qa_response to splice conversation context**

In `src/agents/qa/nodes.py`, replace the `generate_qa_response` function's messages construction:

From:
```python
        reply = await llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": QA_SYSTEM_PROMPT.format(
                        preferences=json.dumps(state.get("preferences", {}), ensure_ascii=False)
                    ),
                },
                {"role": "user", "content": state["message"]},
            ],
        )
```

To:
```python
        context_parts = []
        if state.get("conversation_summary"):
            context_parts.append(f"你们之前对话的摘要：{state['conversation_summary']}")
        if state.get("recent_messages"):
            context_parts.append("最近对话记录见下方。")
        conversation_context = "\n".join(context_parts) if context_parts else "（暂无历史对话）"

        messages = [
            {
                "role": "system",
                "content": QA_SYSTEM_PROMPT.format(
                    preferences=json.dumps(state.get("preferences", {}), ensure_ascii=False),
                    conversation_context=conversation_context,
                ),
            },
        ]
        for msg in state.get("recent_messages", []):
            messages.append(msg)
        messages.append({"role": "user", "content": state["message"]})

        reply = await llm.chat(messages=messages)
```

- [ ] **Step 3: Update QAAgent.handle() to use ConversationMemory**

In `src/agents/qa/graph.py`, update imports and `handle()` method:

Add imports at top:
```python
from src.memory.conversation import ConversationMemory
```

Replace the `handle()` method:
```python
    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识（"qa" 或 "unknown"）
            message: 用户原始消息文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话

        返回:
            AgentResponse: 包含个性化回复文本的响应
        """
        memory = ConversationMemory(self._llm)
        summary, recent = await memory.get_context(user_id, db)

        initial_state: dict = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "conversation_summary": summary,
            "recent_messages": recent,
        }
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)

        reply = result.get("reply", "")
        await memory.save_exchange(user_id, message, reply, db)
        return AgentResponse(reply=reply, data=result.get("data"))
```

- [ ] **Step 4: Run tests to verify**

Run: `uv run pytest tests/test_qa.py -v`

Expected: PASS (existing tests still work; mock LLM handles extra messages)

- [ ] **Step 5: Commit**

```bash
git add src/agents/qa/nodes.py src/agents/qa/graph.py
git commit -m "feat: add personality prompt and conversation memory to QA agent"
```

---

### Task 5: Fitness Agent — new prompt + memory injection

**Files:**
- Modify: `src/agents/fitness/nodes.py:33-35, 215-243`
- Modify: `src/agents/fitness/graph.py` — `handle()` method

- [ ] **Step 1: Update Fitness PLAN_PROMPT**

In `src/agents/fitness/nodes.py`, replace `PLAN_PROMPT` (the `today_plan` prompt):

```python
PLAN_PROMPT = """你是"铁块教练"，用户的私人健身教练。

性格底色：热血、直接、有股子"再来一组"的劲头，但说到安全动作时就切回认真模式。

说话方式：
- 用老铁/兄弟称呼，别太频繁
- 鼓励要有，但不尬吹——用户划水了也要点出来
- 讲动作细节时切换成简洁清晰的专业口吻
- 可以加 💪 🔥 这类 emoji

回复长度：训练建议 3-5 句，打卡确认 1-2 句。

根据用户最近的训练记录和偏好，生成今日训练建议。
考虑：部位轮换（避免连续练同一部位）、用户目标和水平。

{conversation_context}"""
```

- [ ] **Step 2: Update generate_plan to splice context**

In `src/agents/fitness/nodes.py`, replace the `generate_plan` function's messages construction:

```python
        context_parts = []
        if state.get("conversation_summary"):
            context_parts.append(f"你们之前对话的摘要：{state['conversation_summary']}")
        conversation_context = "\n".join(context_parts) if context_parts else ""

        messages = [
            {
                "role": "system",
                "content": PLAN_PROMPT.format(
                    conversation_context=conversation_context,
                ),
            },
        ]
        for msg in state.get("recent_messages", []):
            messages.append(msg)
        messages.append({
            "role": "user",
            "content": (
                f"用户偏好：{json.dumps(prefs.get('fitness', {}), ensure_ascii=False)}\n"
                f"最近训练：\n{state.get('history_text', '暂无训练记录')}\n"
                f"请给出今日训练建议。"
            ),
        })

        reply = await llm.chat(messages=messages)
```

- [ ] **Step 3: Update FitnessAgent.handle() to use ConversationMemory**

In `src/agents/fitness/graph.py`, add import:
```python
from src.memory.conversation import ConversationMemory
```

Replace `handle()`:
```python
    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识（"log_training" 或 "today_plan"）
            message: 用户原始消息文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话

        返回:
            AgentResponse: 包含自然语言回复和可选结构化数据的响应
        """
        memory = ConversationMemory(self._llm)

        # 仅 today_plan 路径加载记忆上下文
        summary = None
        recent = []
        if intent == "today_plan":
            summary, recent = await memory.get_context(user_id, db)

        initial_state: dict = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "conversation_summary": summary,
            "recent_messages": recent,
        }
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)

        reply = result.get("reply", "")
        if intent == "today_plan":
            await memory.save_exchange(user_id, message, reply, db)
        return AgentResponse(reply=reply, data=result.get("data"))
```

- [ ] **Step 4: Run tests to verify**

Run: `uv run pytest tests/test_fitness.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/fitness/nodes.py src/agents/fitness/graph.py
git commit -m "feat: add personality prompt and conversation memory to Fitness agent"
```

---

### Task 6: Meal Agent — new prompt + memory injection

**Files:**
- Modify: `src/agents/meal/nodes.py:17-30, 71-98`
- Modify: `src/agents/meal/graph.py` — `handle()` method

- [ ] **Step 1: Update MEAL_PROMPT**

In `src/agents/meal/nodes.py`, replace `MEAL_PROMPT`:

```python
MEAL_PROMPT = """你是"小厨"，用户的私人营养顾问。

性格底色：细心、讲究、对食物有热情，聊到好吃的会兴奋但不过分。

说话方式：
- 讲营养知识时像科普博主：易懂、有趣、不吓人
- 推荐食谱时带一点画面感（"鸡胸肉煎到两面金黄..."）
- 理解用户的饮食偏好和禁忌，不强行说教
- 偶尔用 🍳 🥗 这类食物 emoji

回复长度：一日三餐推荐 5-8 句，简单问答 2-3 句。

根据用户信息和最近训练情况，生成一日三餐食谱。

要求：
- 每餐给出具体食物和营养素估算（蛋白质、碳水、脂肪、卡路里）
- 考虑用户热量目标、饮食类型、过敏原
- 有训练日提高蛋白质比例
- 用中文输出，格式如下：

早餐 (≈XXX kcal)
- 食物名 (蛋白质Xg, 碳水Xg, 脂肪Xg)
午餐 (≈XXX kcal)
- ...
晚餐 (≈XXX kcal)
- ...

{conversation_context}"""
```

- [ ] **Step 2: Update generate_meal_plan to splice context**

In `src/agents/meal/nodes.py`, replace the `generate_meal_plan` function's messages construction:

```python
        context_parts = []
        if state.get("conversation_summary"):
            context_parts.append(f"你们之前对话的摘要：{state['conversation_summary']}")
        conversation_context = "\n".join(context_parts) if context_parts else ""

        messages = [
            {
                "role": "system",
                "content": MEAL_PROMPT.format(
                    conversation_context=conversation_context,
                ),
            },
        ]
        for msg in state.get("recent_messages", []):
            messages.append(msg)
        messages.append({"role": "user", "content": context})

        reply = await llm.chat(messages=messages)
```

- [ ] **Step 3: Update MealAgent.handle() to use ConversationMemory**

In `src/agents/meal/graph.py`, add import:
```python
from src.memory.conversation import ConversationMemory
```

Replace `handle()`:
```python
    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识（"make_meal_plan"）
            message: 用户原始消息文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话

        返回:
            AgentResponse: 包含一日三餐食谱文本的响应
        """
        memory = ConversationMemory(self._llm)
        summary, recent = await memory.get_context(user_id, db)

        initial_state: dict = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "conversation_summary": summary,
            "recent_messages": recent,
        }
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)

        reply = result.get("reply", "")
        await memory.save_exchange(user_id, message, reply, db)
        return AgentResponse(reply=reply, data=result.get("data"))
```

- [ ] **Step 4: Run tests to verify**

Run: `uv run pytest tests/test_meal.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/meal/nodes.py src/agents/meal/graph.py
git commit -m "feat: add personality prompt and conversation memory to Meal agent"
```

---

### Task 7: Summary Agent prompt update

**Files:**
- Modify: `src/agents/summary/nodes.py:11, 23`

- [ ] **Step 1: Update SUMMARY_PROMPT and GROUP_SUMMARY_PROMPT**

In `src/agents/summary/nodes.py`, update the first line of both prompts:

`SUMMARY_PROMPT` — add style guidance:
```python
SUMMARY_PROMPT = """你是群聊总结助手。风格：客观、条理清晰、抓住重点，不添油加醋。
用以下格式总结用户提供的聊天记录：
..."""
```

`GROUP_SUMMARY_PROMPT` — add style guidance:
```python
GROUP_SUMMARY_PROMPT = """你是群聊总结助手。风格：客观、条理清晰、抓住重点，不添油加醋。
以下是一条一条的群聊消息记录，按时间顺序排列，每条格式为 [发送者]: 内容。
..."""
```

- [ ] **Step 2: Run tests to verify**

Run: `uv run pytest tests/test_summary.py tests/test_e2e_group_summary.py -v`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/agents/summary/nodes.py
git commit -m "refine: update summary agent prompts with style guidance"
```

---

### Task 8: Register conversation models and ensure DB init

**Files:**
- Modify: `src/models/__init__.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Import conversation models for table registration**

Verify `src/models/__init__.py` imports the new models (or add if missing):

```python
import src.models.conversation  # noqa: F401
```

Check that `tests/conftest.py` already has `import src.models  # noqa: F401` (it does, confirmed earlier). The `conversation.py` models inherit from `Base`, so they are auto-discovered.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -q`

Expected: all tests PASS (88 original + ~8 new = ~96)

- [ ] **Step 3: Commit**

```bash
git add src/models/__init__.py
git commit -m "chore: register conversation models for DB initialization"
```

---

### Task 9: Documentation update

**Files:**
- Modify: `docs/agent/active-context.md`

- [ ] **Step 1: Add to "What Is Implemented"**

In `docs/agent/active-context.md`, add after the voice message line:

```
- Agent personality: each agent (QA/小管家, Fitness/铁块教练, Meal/小厨, Summary/会议纪要员) has a distinct persona with defined character, speaking style, and emotional tone.
- Conversation memory: 6-turn recent messages + LLM-compressed summary persisted to SQLite; QA, Fitness(today_plan), and Meal agents maintain cross-turn context.
```

- [ ] **Step 2: Commit**

```bash
git add docs/agent/active-context.md
git commit -m "docs: add agent personality and conversation memory to active context"
```
