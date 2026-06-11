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
        self._embedding = embedding_service or EmbeddingService()

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
        embedding = await self._embedding.embed(content)
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
        memory.embedding_json = json.dumps(await self._embedding.embed(new_content))
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

        query_vec = await self._embedding.embed(query)
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
