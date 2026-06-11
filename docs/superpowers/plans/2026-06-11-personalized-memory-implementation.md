# 个性化记忆功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 bot 记住用户偏好和事实，跨会话持久化，后续对话通过语义向量检索自动引用。

**Architecture:** 新增 UserMemory ORM + MemoryService（CRUD + 语义检索 + 自动提取），PrivateButlerAgent 新增 memory tools 和 prompt 注入。复用现有 `EmbeddingService`。

**Tech Stack:** Python 3.13+, SQLAlchemy 2 async, 复用 `src/knowledge/embedding.py`

---

### Task 1: 创建 UserMemory ORM 模型

**Files:**
- Create: `src/agents/memory/models.py`
- Modify: `src/models/__init__.py`

- [ ] **Step 1: 创建 models.py**

```python
"""
个性化记忆 ORM 模型
存储用户偏好和事实，每条记忆独立存储，通过 embedding 支持语义检索。

Workflow:
1. MemoryService.add_memory() 写入 UserMemory
2. MemoryService.search() 通过 embedding 相似度检索 top-K 相关记忆
3. MemoryService.list_memories() / update_memory() / delete_memory() 管理记忆
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from src.db.base import Base


class UserMemory(Base):
    """用户个性化记忆表"""

    __tablename__ = "user_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    user_id = Column(String(256), nullable=False, index=True)
    """记忆归属的用户 ID"""

    content = Column(Text, nullable=False)
    """记忆文本，如"用户不喝咖啡，偏好喝茶" """

    embedding_json = Column(Text, nullable=True)
    """向量嵌入，JSON 序列化存储，用于语义检索"""

    source = Column(String(32), nullable=False, default="explicit")
    """来源：explicit（显式"记住：..."）/ extracted（自动提取）"""

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    """创建时间"""

    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    """最后更新时间"""
```

- [ ] **Step 2: 更新 models/__init__.py 导出**

在现有 import 区新增：
```python
from src.agents.memory.models import UserMemory
```

在 `__all__` 中新增 `"UserMemory"`。

- [ ] **Step 3: 提交**

```bash
git add src/agents/memory/models.py src/models/__init__.py
git commit -m "feat: add UserMemory ORM model"
```

---

### Task 2: 创建 MemoryService

**Files:**
- Create: `src/agents/memory/__init__.py`
- Create: `src/agents/memory/service.py`

- [ ] **Step 1: 创建 __init__.py**

```python
"""个性化记忆包，提供记忆的增删改查和语义检索"""
from src.agents.memory.service import MemoryService

__all__ = ["MemoryService"]
```

- [ ] **Step 2: 创建 service.py**

```python
"""
个性化记忆服务
提供记忆的增删改查、语义检索和自动事实提取。

Workflow:
  MemoryService.add_memory() → 生成 embedding → 写入 UserMemory
  MemoryService.search() → 计算相似度 → 返回 top-K
  MemoryService.extract_facts() → LLM 扫描对话 → 返回候选事实
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.memory.models import UserMemory
from src.knowledge.embedding import EmbeddingService

logger = logging.getLogger(__name__)

EXTRACT_FACTS_PROMPT = """你是用户信息提取器。从以下对话中提取关于用户的偏好、习惯、身份、喜好等事实。

对话记录：
{transcript}

规则：
- 只提取关于用户本人（user 角色）的事实，不提取关于其他人的
- 每行一个事实，格式："用户xxx"
- 不提取临时、一次性的信息（如"我今天想吃饭"）
- 只提取有长期价值的信息（如"用户不喜欢咖啡"、"用户在北京工作"）
- 没有值得记录的事实时，返回空字符串""

事实列表（每行一个）："""


class MemoryService:
    """个性化记忆服务"""

    def __init__(self, embedding_service: EmbeddingService | None = None):
        """初始化记忆服务

        参数:
            embedding_service: 嵌入服务；未注入时使用默认 256 维

        返回:
            None
        """
        self._embedding = embedding_service or EmbeddingService(256)

    # ── CRUD ──────────────────────────────────────────

    async def add_memory(
        self, db: AsyncSession, user_id: str, content: str, source: str = "explicit"
    ) -> UserMemory:
        """添加一条个性化记忆

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            content: 记忆文本
            source: 来源，explicit 或 extracted

        返回:
            UserMemory: 新创建的记忆对象
        """
        embedding = self._embedding.embed(content)
        memory = UserMemory(
            user_id=user_id,
            content=content,
            embedding_json=json.dumps(embedding),
            source=source,
        )
        db.add(memory)
        await db.flush()
        logger.info("Memory: added for user_id=%s source=%s content=%s", user_id, source, content[:80])
        return memory

    async def list_memories(self, db: AsyncSession, user_id: str) -> list[UserMemory]:
        """列出用户的所有记忆

        参数:
            db: 异步数据库会话
            user_id: 用户 ID

        返回:
            list[UserMemory]: 该用户的所有记忆
        """
        result = await db.execute(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.updated_at.desc())
        )
        return list(result.scalars().all())

    async def update_memory(
        self, db: AsyncSession, memory_id: int, user_id: str, new_content: str
    ) -> UserMemory | None:
        """更新记忆内容并重新生成 embedding

        参数:
            db: 异步数据库会话
            memory_id: 记忆 ID
            user_id: 请求用户 ID（权限校验）
            new_content: 新的记忆内容

        返回:
            UserMemory | None: 更新后的记忆；无权限或不存在时返回 None
        """
        result = await db.execute(
            select(UserMemory).where(UserMemory.id == memory_id)
        )
        memory = result.scalar_one_or_none()
        if memory is None or memory.user_id != user_id:
            return None
        memory.content = new_content
        memory.embedding_json = json.dumps(self._embedding.embed(new_content))
        memory.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.flush()
        logger.info("Memory: updated id=%s for user_id=%s", memory_id, user_id)
        return memory

    async def delete_memory(
        self, db: AsyncSession, memory_id: int, user_id: str
    ) -> bool:
        """删除记忆

        参数:
            db: 异步数据库会话
            memory_id: 记忆 ID
            user_id: 请求用户 ID（权限校验）

        返回:
            bool: 是否成功删除
        """
        result = await db.execute(
            delete(UserMemory).where(
                UserMemory.id == memory_id,
                UserMemory.user_id == user_id,
            )
        )
        await db.flush()
        deleted = result.rowcount > 0
        if deleted:
            logger.info("Memory: deleted id=%s for user_id=%s", memory_id, user_id)
        return deleted

    # ── 语义检索 ─────────────────────────────────────────

    async def search(
        self, db: AsyncSession, user_id: str, query: str, top_k: int = 3, threshold: float = 0.5
    ) -> list[dict]:
        """语义检索与查询最相关的记忆

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            query: 查询文本（通常为用户当前消息）
            top_k: 返回的最多条数
            threshold: 余弦相似度阈值，低于此值的记忆不返回

        返回:
            list[dict]: [{"id": 1, "content": "...", "similarity": 0.85}, ...]
        """
        result = await db.execute(
            select(UserMemory).where(UserMemory.user_id == user_id)
        )
        memories = result.scalars().all()
        if not memories:
            return []

        query_vec = self._embedding.embed(query)
        scored = []
        for m in memories:
            if m.embedding_json is None:
                continue
            try:
                mem_vec = json.loads(m.embedding_json)
            except (json.JSONDecodeError, TypeError):
                continue
            sim = self._embedding.similarity(query_vec, mem_vec)
            if sim >= threshold:
                scored.append({"id": m.id, "content": m.content, "similarity": sim})

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]

    # ── 自动提取 ─────────────────────────────────────────

    async def extract_facts(
        self, db: AsyncSession, user_id: str, transcript: str, llm
    ) -> list[UserMemory]:
        """从对话记录中自动提取用户事实

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            transcript: 对话记录文本
            llm: LLMClient 实例

        返回:
            list[UserMemory]: 新提取并已存储的记忆列表
        """
        raw = await llm.chat(
            messages=[
                {"role": "system", "content": "只返回事实列表，每行一个，不要返回其他内容。"},
                {"role": "user", "content": EXTRACT_FACTS_PROMPT.format(transcript=transcript)},
            ],
            temperature=0.2,
        )

        facts = [line.strip() for line in raw.strip().split("\n") if line.strip()]
        existing = await self.list_memories(db, user_id)
        existing_contents = {m.content for m in existing}

        new_memories = []
        for fact in facts:
            if fact not in existing_contents:
                memory = await self.add_memory(db, user_id, fact, source="extracted")
                new_memories.append(memory)

        if new_memories:
            logger.info("Memory: extracted %s facts for user_id=%s", len(new_memories), user_id)
        return new_memories
```

- [ ] **Step 3: 提交**

```bash
git add src/agents/memory/__init__.py src/agents/memory/service.py
git commit -m "feat: add MemoryService with CRUD, search, and fact extraction"
```

---

### Task 3: PrivateButlerAgent 新增 memory tools

**Files:**
- Modify: `src/agents/private_butler/tools.py`

- [ ] **Step 1: 新增 memory tools**

在文件顶部 import 区新增：
```python
from src.agents.memory.service import MemoryService
```

在 `PrivateButlerToolContext` dataclass 中新增字段（在 `reminder_agent` 之后）：
```python
memory_service: Any = None
```

在 `_runtime()` 函数之后新增 memory 工具辅助函数：
```python
def _get_memory_service(context: PrivateButlerToolContext):
    """获取 memory service，未注入时返回 None"""
    return context.memory_service
```

在 `cancel_reminder` tool 之后、`return` 列表之前，新增 5 个 memory tools：

```python
@tool
async def add_memory(content: str) -> str:
    """添加一条关于用户的个性化记忆

    参数:
        content: 记忆内容，例如"用户不喝咖啡，偏好喝茶"

    返回:
        str: 添加结果
    """
    db, user_id, _, _ = _runtime()
    service = _get_memory_service(context)
    if service is None:
        return "记忆功能暂不可用。"
    memory = await service.add_memory(db, user_id, content, source="explicit")
    return f"已记住：{memory.content}"


@tool
async def list_memories(message: str = "") -> str:
    """查看当前用户的所有个性化记忆

    参数:
        message: 用户查看请求，可忽略

    返回:
        str: 记忆列表
    """
    db, user_id, _, _ = _runtime()
    service = _get_memory_service(context)
    if service is None:
        return "记忆功能暂不可用。"
    memories = await service.list_memories(db, user_id)
    if not memories:
        return "你还没有保存过记忆。可以跟我说"记住：xxx"来添加。"
    lines = [f"{i+1}. {m.content}" for i, m in enumerate(memories)]
    return "我记得以下关于你的信息：\n" + "\n".join(lines)


@tool
async def update_memory(memory_id: int, new_content: str) -> str:
    """更新一条个性化记忆

    参数:
        memory_id: 记忆编号（从 list_memories 获取）
        new_content: 新的记忆内容

    返回:
        str: 更新结果
    """
    db, user_id, _, _ = _runtime()
    service = _get_memory_service(context)
    if service is None:
        return "记忆功能暂不可用。"
    memory = await service.update_memory(db, memory_id, user_id, new_content)
    if memory is None:
        return f"没有找到编号为 {memory_id} 的记忆，或你没有权限修改。"
    return f"已更新：{memory.content}"


@tool
async def delete_memory(memory_id: int) -> str:
    """删除一条个性化记忆

    参数:
        memory_id: 记忆编号（从 list_memories 获取）

    返回:
        str: 删除结果
    """
    db, user_id, _, _ = _runtime()
    service = _get_memory_service(context)
    if service is None:
        return "记忆功能暂不可用。"
    ok = await service.delete_memory(db, memory_id, user_id)
    if not ok:
        return f"没有找到编号为 {memory_id} 的记忆，或你没有权限删除。"
    return f"已删除编号为 {memory_id} 的记忆。"


@tool
async def search_memory(query: str) -> str:
    """搜索与用户查询相关的个性化记忆

    参数:
        query: 要搜索的关键词或问题

    返回:
        str: 相关的记忆内容
    """
    db, user_id, _, _ = _runtime()
    service = _get_memory_service(context)
    if service is None:
        return "记忆功能暂不可用。"
    results = await service.search(db, user_id, query)
    if not results:
        return "没有找到相关记忆。"
    lines = [f"- {r['content']}" for r in results]
    return "相关记忆：\n" + "\n".join(lines)
```

在 return 列表中新增：
```python
add_memory, list_memories, update_memory, delete_memory, search_memory,
```

- [ ] **Step 2: 提交**

```bash
git add src/agents/private_butler/tools.py
git commit -m "feat: add memory tools to PrivateButlerAgent"
```

---

### Task 4: System prompt 注入 memory context

**Files:**
- Modify: `src/agents/private_butler/prompts.py`
- Modify: `src/agents/private_butler/nodes.py`
- Modify: `src/agents/private_butler/graph.py`
- Modify: `src/agents/private_butler/state.py`

- [ ] **Step 1: prompts.py — 新增 memory context 占位**

在 `PRIVATE_BUTLER_SYSTEM_PROMPT` 的末尾（`{recent_messages}` 之前或之后），新增 memory 段：

```python
已知用户信息：
{memory_context}
```

完整 prompt 新增位置（在"历史摘要"之前）：
```python
PRIVATE_BUTLER_SYSTEM_PROMPT = """你是"小管家"，用户私聊里的总控私人助理。

...

已知用户信息：
{memory_context}

历史摘要：
{conversation_summary}

最近对话：
{recent_messages}"""
```

更新 `build_system_prompt` 函数签名和调用：
```python
def build_system_prompt(
    conversation_summary: str | None,
    recent_messages: list[dict] | None,
    memory_context: str = "",
) -> str:
    ...
    return PRIVATE_BUTLER_SYSTEM_PROMPT.format(
        conversation_summary=summary_text,
        recent_messages=recent_text,
        memory_context=memory_context or "（暂无已知信息）",
    )
```

- [ ] **Step 2: state.py — 新增 memory_context 字段**

在 `PrivateButlerState` 中新增：
```python
memory_context: str
"""个性化记忆上下文，由 handle() 注入"""
```

- [ ] **Step 3: nodes.py — call_model 传递 memory_context**

在 `call_model` 中调用 `build_system_prompt` 时新增参数：
```python
content=build_system_prompt(
    state.get("conversation_summary"),
    state.get("recent_messages", []),
    memory_context=state.get("memory_context", ""),
)
```

- [ ] **Step 4: graph.py — handle() 检索记忆并注入**

在 `PrivateButlerAgent.__init__` 中新增参数：
```python
def __init__(self, ..., memory_service=None):
    ...
    self._memory_service = memory_service
```

在 `handle()` 方法中，构建 `initial_state` 之前，检索相关记忆：
```python
# 检索个性化记忆
memory_context = ""
if self._memory_service is not None:
    results = await self._memory_service.search(db, user_id, message, top_k=3, threshold=0.5)
    if results:
        lines = [f"- {r['content']}" for r in results]
        memory_context = "\n".join(lines)

initial_state: dict = {
    ...
    "memory_context": memory_context,
    ...
}
```

- [ ] **Step 5: 提交**

```bash
git add src/agents/private_butler/prompts.py src/agents/private_butler/state.py src/agents/private_butler/nodes.py src/agents/private_butler/graph.py
git commit -m "feat: inject personalized memory context into PrivateButlerAgent prompt"
```

---

### Task 5: main.py 注入 MemoryService

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: 初始化 MemoryService 并注入**

导入：
```python
from src.agents.memory import MemoryService
```

在 `private_butler_agent` 创建之前，新增：
```python
memory_service = MemoryService()
```

更新 `PrivateButlerAgent` 构造函数调用，新增 `memory_service=memory_service`：
```python
private_butler_agent = PrivateButlerAgent(
    llm_client=llm_client,
    summary_agent=summary_agent,
    knowledge_service=knowledge_service,
    web_search_service=web_search_service,
    weather_service=weather_service,
    reminder_agent=reminder_agent,
    memory_service=memory_service,
)
```

- [ ] **Step 2: 提交**

```bash
git add src/main.py
git commit -m "feat: wire MemoryService into main app"
```

---

### Task 6: 集成验证

**Files:**
- 无新文件

- [ ] **Step 1: 验证导入和能力**

```bash
cd /Users/assle/dev/personal_butler_agent
uv run python -c "
from src.agents.memory.models import UserMemory
from src.agents.memory import MemoryService
from src.agents.private_butler.tools import create_private_butler_tools
print('All imports OK')
"
```

- [ ] **Step 2: 验证 embedding + 检索**

```bash
uv run python -c "
from src.knowledge.embedding import EmbeddingService
from src.agents.memory.service import MemoryService
svc = MemoryService(EmbeddingService(256))

# 模拟几条记忆的相似度
v1 = svc._embedding.embed('用户不喝咖啡')
v2 = svc._embedding.embed('不喜欢咖啡')
v3 = svc._embedding.embed('用户在北京工作')
sim1 = svc._embedding.similarity(v1, v2)
sim2 = svc._embedding.similarity(v1, v3)
assert sim1 > sim2, f'Expected sim1 > sim2, got {sim1:.3f} vs {sim2:.3f}'
print(f'Semantic similarity OK: 咖啡相关={sim1:.3f}, 无关={sim2:.3f}')
"
```

- [ ] **Step 3: 运行现有测试**

```bash
uv run pytest tests/ -x -q
```

Expected: 全部通过

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "chore: verify personalized memory integration"
```
