"""
个性化记忆服务
提供碎片写入、聚合升级、画像 CRUD、重要性计算、衰减和语义检索。

Workflow:
  extractor 提取碎片 → add_fragment() 写入 memory_fragments
  → aggregate_fragments() 检查 occurrences ≥ 3 → 升级为 UserProfile
  → search_profiles() 语义检索 top-K 确认画像
  → decay_profiles() 定期衰减低重要性画像
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.memory.models import MemoryFragment, UserMemory, UserProfile
from src.knowledge.embedding import EmbeddingService

logger = logging.getLogger(__name__)

# 类型 → 信号强度默认值
_TYPE_SIGNAL_STRENGTH = {
    "preference": 0.9,
    "fact": 0.5,
    "habit": 0.3,
    "relationship": 0.4,
}

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
    """个性化记忆服务——碎片池 + 确认画像双层管理"""

    def __init__(self, embedding_service: EmbeddingService | None = None):
        """初始化记忆服务

        参数:
            embedding_service: 嵌入服务；未注入时使用默认实例

        返回:
            None
        """
        self._embedding = embedding_service or EmbeddingService()

    # ── 碎片管理 ──────────────────────────────────────────

    async def add_fragment(
        self,
        db: AsyncSession,
        user_id: str,
        fragment_type: str,
        content: str,
        signal_strength: float = 0.5,
    ) -> MemoryFragment | None:
        """写入或更新一条画像碎片

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            fragment_type: 碎片类型（preference/fact/habit/relationship）
            content: 碎片文本
            signal_strength: 信号强度 0.0~1.0

        返回:
            MemoryFragment | None: 新建或更新后的碎片；类型非法时返回 None
        """
        if fragment_type not in _TYPE_SIGNAL_STRENGTH:
            logger.warning("Memory: invalid fragment type=%s", fragment_type)
            return None

        # 检查是否已有语义相似的碎片
        existing = await self._find_similar_fragment(db, user_id, fragment_type, content)
        if existing is not None:
            existing.occurrences += 1
            existing.last_seen_at = datetime.now(timezone.utc)
            existing.signal_strength = max(existing.signal_strength, signal_strength)
            await db.flush()
            logger.info(
                "Memory: fragment updated id=%s occurrences=%s content=%s",
                existing.id, existing.occurrences, content[:80],
            )
            return existing

        now = datetime.now(timezone.utc)
        fragment = MemoryFragment(
            user_id=user_id,
            type=fragment_type,
            content=content,
            signal_strength=signal_strength,
            occurrences=1,
            last_seen_at=now,
            created_at=now,
        )
        db.add(fragment)
        await db.flush()
        logger.info("Memory: fragment created type=%s content=%s", fragment_type, content[:80])
        return fragment

    async def _find_similar_fragment(
        self, db: AsyncSession, user_id: str, fragment_type: str, content: str
    ) -> MemoryFragment | None:
        """查找与给定内容语义相似的已有碎片

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            fragment_type: 碎片类型
            content: 新碎片文本

        返回:
            MemoryFragment | None: 相似碎片或 None
        """
        result = await db.execute(
            select(MemoryFragment).where(
                MemoryFragment.user_id == user_id,
                MemoryFragment.type == fragment_type,
            )
        )
        fragments = result.scalars().all()
        if not fragments:
            return None

        query_vec = await self._embedding.embed(content)
        for f in fragments:
            fragment_vec = await self._embedding.embed(f.content)
            sim = self._embedding.similarity(query_vec, fragment_vec)
            if sim >= 0.85:
                return f
        return None

    # ── 聚合升级 ──────────────────────────────────────────

    async def aggregate_fragments(
        self, db: AsyncSession, user_id: str
    ) -> list[UserProfile]:
        """扫描碎片池，将 occurrences ≥ 3 的碎片升级为确认画像

        参数:
            db: 异步数据库会话
            user_id: 用户 ID

        返回:
            list[UserProfile]: 新升级的画像条目列表
        """
        result = await db.execute(
            select(MemoryFragment).where(
                MemoryFragment.user_id == user_id,
                MemoryFragment.occurrences >= 3,
            )
        )
        ready_fragments = result.scalars().all()
        if not ready_fragments:
            return []

        new_profiles: list[UserProfile] = []
        for fragment in ready_fragments:
            existing = await self._find_profile_by_content(
                db, user_id, fragment.type, fragment.content
            )
            if existing is not None:
                existing.confidence = min(1.0, existing.confidence + 0.15)
                existing.importance = self._calculate_importance(
                    existing.source, existing.confidence, existing.type
                )
                existing.updated_at = datetime.now(timezone.utc)
                existing.decayed_at = None
                logger.info("Memory: profile updated id=%s confidence=%.2f", existing.id, existing.confidence)
            else:
                confidence = min(1.0, fragment.occurrences * 0.2)
                profile = UserProfile(
                    user_id=user_id,
                    type=fragment.type,
                    content=fragment.content,
                    confidence=confidence,
                    importance=self._calculate_importance("implicit", confidence, fragment.type),
                    source="implicit",
                    embedding_json=json.dumps(await self._embedding.embed(fragment.content)),
                )
                db.add(profile)
                await db.flush()
                new_profiles.append(profile)
                logger.info("Memory: profile created type=%s content=%s", fragment.type, fragment.content[:80])

            # 删除已升级的碎片
            await db.delete(fragment)

        await db.flush()
        return new_profiles

    async def _find_profile_by_content(
        self, db: AsyncSession, user_id: str, profile_type: str, content: str
    ) -> UserProfile | None:
        """查找与给定内容语义相似的已有画像

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            profile_type: 画像类型
            content: 待匹配文本

        返回:
            UserProfile | None
        """
        result = await db.execute(
            select(UserProfile).where(
                UserProfile.user_id == user_id,
                UserProfile.type == profile_type,
                UserProfile.decayed_at == None,
            )
        )
        profiles = result.scalars().all()
        if not profiles:
            return None

        query_vec = await self._embedding.embed(content)
        for p in profiles:
            if p.embedding_json is None:
                continue
            try:
                p_vec = json.loads(p.embedding_json)
            except (json.JSONDecodeError, TypeError):
                continue
            sim = self._embedding.similarity(query_vec, p_vec)
            if sim >= 0.85:
                return p
        return None

    # ── 画像 CRUD ──────────────────────────────────────────

    async def upsert_profile(
        self,
        db: AsyncSession,
        user_id: str,
        profile_type: str,
        content: str,
        source: str = "explicit",
    ) -> UserProfile:
        """添加或更新一条确认画像（显式记忆入口）

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            profile_type: 画像类型
            content: 画像文本
            source: 来源，explicit 或 implicit

        返回:
            UserProfile: 新建或更新后的画像
        """
        existing = await self._find_profile_by_content(db, user_id, profile_type, content)
        if existing is not None:
            existing.content = content
            existing.source = source
            existing.confidence = 1.0 if source == "explicit" else existing.confidence
            existing.importance = self._calculate_importance(
                source, existing.confidence, profile_type
            )
            existing.embedding_json = json.dumps(await self._embedding.embed(content))
            existing.updated_at = datetime.now(timezone.utc)
            existing.decayed_at = None
            await db.flush()
            logger.info("Memory: profile upserted id=%s", existing.id)
            return existing

        now = datetime.now(timezone.utc)
        confidence = 1.0 if source == "explicit" else 0.6
        profile = UserProfile(
            user_id=user_id,
            type=profile_type,
            content=content,
            confidence=confidence,
            importance=self._calculate_importance(source, confidence, profile_type),
            source=source,
            embedding_json=json.dumps(await self._embedding.embed(content)),
            created_at=now,
            updated_at=now,
        )
        db.add(profile)
        await db.flush()
        logger.info("Memory: profile created source=%s type=%s content=%s", source, profile_type, content[:80])
        return profile

    async def list_profiles(
        self, db: AsyncSession, user_id: str, include_decayed: bool = False
    ) -> list[UserProfile]:
        """列出用户的有效画像

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            include_decayed: 是否包含已衰减的画像

        返回:
            list[UserProfile]: 画像列表，按重要性降序
        """
        query = select(UserProfile).where(UserProfile.user_id == user_id)
        if not include_decayed:
            query = query.where(UserProfile.decayed_at == None)
        query = query.order_by(UserProfile.importance.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    async def update_profile(
        self, db: AsyncSession, profile_id: int, user_id: str, new_content: str
    ) -> UserProfile | None:
        """更新画像内容并重新生成 embedding

        参数:
            db: 异步数据库会话
            profile_id: 画像 ID
            user_id: 请求用户 ID（权限校验）
            new_content: 新内容

        返回:
            UserProfile | None
        """
        result = await db.execute(
            select(UserProfile).where(UserProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None or profile.user_id != user_id:
            return None
        profile.content = new_content
        profile.embedding_json = json.dumps(await self._embedding.embed(new_content))
        profile.updated_at = datetime.now(timezone.utc)
        profile.importance = self._calculate_importance(
            profile.source, profile.confidence, profile.type
        )
        await db.flush()
        logger.info("Memory: profile updated id=%s", profile_id)
        return profile

    async def delete_profile(
        self, db: AsyncSession, profile_id: int, user_id: str
    ) -> bool:
        """删除画像

        参数:
            db: 异步数据库会话
            profile_id: 画像 ID
            user_id: 请求用户 ID

        返回:
            bool: 是否成功删除
        """
        result = await db.execute(
            delete(UserProfile).where(
                UserProfile.id == profile_id,
                UserProfile.user_id == user_id,
            )
        )
        await db.flush()
        deleted = result.rowcount > 0
        if deleted:
            logger.info("Memory: profile deleted id=%s", profile_id)
        return deleted

    # ── 语义检索 ──────────────────────────────────────────

    async def search_profiles(
        self,
        db: AsyncSession,
        user_id: str,
        query: str,
        top_k: int = 3,
        threshold: float = 0.5,
    ) -> list[dict]:
        """语义检索与查询最相关的确认画像

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            query: 查询文本
            top_k: 返回最多条数
            threshold: 余弦相似度阈值

        返回:
            list[dict]: [{"id": 1, "type": "preference", "content": "...", "similarity": 0.85}, ...]
        """
        profiles = await self.list_profiles(db, user_id)
        if not profiles:
            return []

        query_vec = await self._embedding.embed(query)
        scored = []
        for p in profiles:
            if p.embedding_json is None:
                continue
            try:
                p_vec = json.loads(p.embedding_json)
            except (json.JSONDecodeError, TypeError):
                continue
            sim = self._embedding.similarity(query_vec, p_vec)
            # 按重要性加权
            weighted_sim = sim * (0.6 + 0.4 * p.importance)
            if weighted_sim >= threshold:
                scored.append({
                    "id": p.id,
                    "type": p.type,
                    "content": p.content,
                    "similarity": weighted_sim,
                    "importance": p.importance,
                    "confidence": p.confidence,
                })

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]

    async def get_profiles_grouped(
        self, db: AsyncSession, user_id: str
    ) -> dict[str, list[dict]]:
        """按类型分组返回用户所有有效画像，用于 prompt 注入

        参数:
            db: 异步数据库会话
            user_id: 用户 ID

        返回:
            dict[str, list[dict]]: {"preference": [...], "fact": [...], "habit": [...], "relationship": [...]}
        """
        profiles = await self.list_profiles(db, user_id)
        grouped: dict[str, list[dict]] = {
            "preference": [],
            "fact": [],
            "habit": [],
            "relationship": [],
        }
        for p in profiles:
            if p.type in grouped:
                grouped[p.type].append({
                    "id": p.id,
                    "content": p.content,
                    "confidence": p.confidence,
                    "importance": p.importance,
                })
        return grouped

    # ── 重要性计算 ──────────────────────────────────────────

    def _calculate_importance(self, source: str, confidence: float, profile_type: str) -> float:
        """计算画像重要性

        公式: source_weight × 0.4 + confidence × 0.4 + signal_strength × 0.2

        参数:
            source: explicit 或 implicit
            confidence: 置信度 0.0~1.0
            profile_type: 画像类型

        返回:
            float: 重要性 0.0~1.0
        """
        source_weight = 1.0 if source == "explicit" else 0.5
        signal_strength = _TYPE_SIGNAL_STRENGTH.get(profile_type, 0.5)
        return round(source_weight * 0.4 + confidence * 0.4 + signal_strength * 0.2, 4)

    # ── 衰减 ──────────────────────────────────────────────

    async def decay_profiles(self, db: AsyncSession, user_id: str) -> int:
        """对用户画像执行衰减，重要性降至 0.1 以下标记为 decayed

        衰减公式:
          decay_rate = 0.01 - importance × 0.009（范围 0.001 ~ 0.01 每天）
          decayed_importance = importance - days_since_update × decay_rate

        参数:
            db: 异步数据库会话
            user_id: 用户 ID

        返回:
            int: 本次衰减掉的画像数量
        """
        profiles = await self.list_profiles(db, user_id)
        now = datetime.now(timezone.utc)
        decayed_count = 0
        for p in profiles:
            days_since_update = max(0, (now - p.updated_at).days)
            decay_rate = 0.01 - p.importance * 0.009
            decayed_importance = p.importance - days_since_update * decay_rate
            if decayed_importance < 0.1:
                p.decayed_at = now
                decayed_count += 1
                logger.info("Memory: profile decayed id=%s content=%s", p.id, p.content[:80])
        await db.flush()
        return decayed_count

    # ── 矛盾检测 ──────────────────────────────────────────

    async def detect_contradiction(
        self,
        db: AsyncSession,
        user_id: str,
        new_content: str,
    ) -> UserProfile | None:
        """检测新信息是否与已有画像矛盾

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            new_content: 新提取的内容文本

        返回:
            UserProfile | None: 存在矛盾的已有画像；无矛盾返回 None
        """
        profiles = await self.list_profiles(db, user_id)
        if not profiles:
            return None

        new_vec = await self._embedding.embed(new_content)
        for p in profiles:
            if p.confidence < 0.6 or p.embedding_json is None:
                continue
            try:
                p_vec = json.loads(p.embedding_json)
            except (json.JSONDecodeError, TypeError):
                continue
            sim = self._embedding.similarity(new_vec, p_vec)
            # 高相似度但内容不同 → 可能是矛盾（需要更高层 LLM 判断）
            if sim > 0.7:
                # 降低已有画像置信度，标记为需澄清
                p.confidence = max(0.3, p.confidence - 0.2)
                p.importance = self._calculate_importance(
                    p.source, p.confidence, p.type
                )
                p.updated_at = datetime.now(timezone.utc)
                await db.flush()
                logger.info("Memory: contradiction detected profile_id=%s", p.id)
                return p
        return None

    # ── 兼容旧接口 ──────────────────────────────────────────

    async def add_memory(
        self, db: AsyncSession, user_id: str, content: str, source: str = "explicit"
    ) -> UserProfile:
        """添加一条个性化记忆（兼容旧接口，内部走 upsert_profile）

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            content: 记忆文本
            source: 来源

        返回:
            UserProfile: 新建或更新后的画像
        """
        profile_type = self._infer_type(content)
        return await self.upsert_profile(db, user_id, profile_type, content, source)

    async def list_memories(self, db: AsyncSession, user_id: str) -> list[UserProfile]:
        """列出用户的所有记忆（兼容旧接口）

        参数:
            db: 异步数据库会话
            user_id: 用户 ID

        返回:
            list[UserProfile]: 有效画像列表
        """
        return await self.list_profiles(db, user_id)

    async def update_memory(
        self, db: AsyncSession, memory_id: int, user_id: str, new_content: str
    ) -> UserProfile | None:
        """更新记忆内容（兼容旧接口）

        参数:
            db: 异步数据库会话
            memory_id: 画像 ID
            user_id: 用户 ID
            new_content: 新内容

        返回:
            UserProfile | None
        """
        return await self.update_profile(db, memory_id, user_id, new_content)

    async def delete_memory(
        self, db: AsyncSession, memory_id: int, user_id: str
    ) -> bool:
        """删除记忆（兼容旧接口）

        参数:
            db: 异步数据库会话
            memory_id: 画像 ID
            user_id: 用户 ID

        返回:
            bool: 是否成功删除
        """
        return await self.delete_profile(db, memory_id, user_id)

    async def search(
        self, db: AsyncSession, user_id: str, query: str, top_k: int = 3, threshold: float = 0.5
    ) -> list[dict]:
        """语义检索记忆（兼容旧接口，内部走 search_profiles）

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            query: 查询文本
            top_k: 返回最多条数
            threshold: 相似度阈值

        返回:
            list[dict]: 搜索结果
        """
        return await self.search_profiles(db, user_id, query, top_k, threshold)

    async def extract_facts(
        self, db: AsyncSession, user_id: str, transcript: str, llm
    ) -> list[UserProfile]:
        """从对话记录中自动提取用户事实（兼容旧接口）

        参数:
            db: 异步数据库会话
            user_id: 用户 ID
            transcript: 对话记录文本
            llm: LLMClient 实例

        返回:
            list[UserProfile]: 新提取并已存储的画像列表
        """
        raw = await llm.chat(
            messages=[
                {"role": "system", "content": "只返回事实列表，每行一个，不要返回其他内容。"},
                {"role": "user", "content": EXTRACT_FACTS_PROMPT.format(transcript=transcript)},
            ],
            temperature=0.2,
        )

        facts = [line.strip() for line in raw.strip().split("\n") if line.strip()]
        result = []
        for fact in facts:
            profile = await self.add_memory(db, user_id, fact, source="extracted")
            result.append(profile)

        if result:
            logger.info("Memory: extracted %s facts for user_id=%s", len(result), user_id)
        return result

    @staticmethod
    def _infer_type(content: str) -> str:
        """从内容推断画像类型

        参数:
            content: 画像文本

        返回:
            str: 画像类型
        """
        preference_keywords = ("喜欢", "不喜欢", "爱", "讨厌", "偏好", "最爱", "不喜欢")
        habit_keywords = ("每天", "经常", "总是", "一直", "从来", "习惯")
        relationship_keywords = ("同事", "朋友", "老板", "领导", "家人", "同学")
        for kw in preference_keywords:
            if kw in content:
                return "preference"
        for kw in habit_keywords:
            if kw in content:
                return "habit"
        for kw in relationship_keywords:
            if kw in content:
                return "relationship"
        return "fact"
