# 深度个性化记忆系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将记忆系统从"被动检索的文本库"升级为 bot 的认知模型——每次对话附带提取画像碎片，碎片聚合为确认画像，画像结构化注入 prompt 并主动指导 bot 行为。

**Architecture:** 双层存储（memory_fragments 碎片池 + user_profile 确认画像），旁路异步提取不阻塞主回复路径，三阶段实施（数据层 → 提取引擎 → 应用层）。复用现有 EmbeddingService，保留 user_memories 表作为过渡。

**Tech Stack:** Python 3.13+, SQLAlchemy 2 async, SQLite, LangChain ChatOpenAI, 现有 EmbeddingService (DashScope Qwen3-Embedding / local fallback)

---

### Task 1: 新增 ORM 模型 MemoryFragment 和 UserProfile

**Files:**
- Modify: `src/agents/memory/models.py`

- [ ] **Step 1: 在 models.py 尾部追加 MemoryFragment 和 UserProfile ORM 类**

在现有 `UserMemory` 类定义之后，追加以下两个新模型：

```python
"""
个性化记忆碎片池 ORM 模型
每次隐式提取的原始信号暂存于此，多次出现后升级为 UserProfile。

Workflow:
  Extractor 提取 → add_fragment() 写入 MemoryFragment
  → 同类型同语义碎片 occurrences ≥ 3 → 聚合升级为 UserProfile
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from src.db.base import Base


class MemoryFragment(Base):
    """记忆碎片池——隐式提取的原始信号"""

    __tablename__ = "memory_fragments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    user_id = Column(String(256), nullable=False, index=True)
    """碎片归属的用户 ID"""

    type = Column(String(32), nullable=False)
    """碎片类型：preference / fact / habit / relationship"""

    content = Column(Text, nullable=False)
    """提取出的原始碎片文本，如\"用户在杭州工作\""""

    signal_strength = Column(Float, nullable=False, default=0.5)
    """信号强度 0.0~1.0，越明确越高"""

    occurrences = Column(Integer, nullable=False, default=1)
    """相同信号出现的累积次数"""

    last_seen_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    """最近一次出现的回调时间"""

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    """首次出现时间"""


class UserProfile(Base):
    """确认画像——碎片聚合后升级的确认记忆"""

    __tablename__ = "user_profile"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    user_id = Column(String(256), nullable=False, index=True)
    """画像归属的用户 ID"""

    type = Column(String(32), nullable=False)
    """画像类型：preference / fact / habit / relationship"""

    content = Column(Text, nullable=False)
    """画像条目文本，如\"用户不喝咖啡，偏好喝茶\""""

    confidence = Column(Float, nullable=False, default=0.6)
    """置信度 0.0~1.0，碎片池中出现次数折算"""

    importance = Column(Float, nullable=False, default=0.5)
    """重要性 0.0~1.0，来源权重×0.4 + 置信度×0.4 + 信号强度×0.2"""

    source = Column(String(32), nullable=False, default="implicit")
    """来源：explicit（用户说\"记住\"）/ implicit（隐式提取）"""

    embedding_json = Column(Text, nullable=True)
    """向量嵌入 JSON，复用 EmbeddingService 生成"""

    related_profile_ids = Column(Text, nullable=True)
    """JSON 数组，关联的其他画像条目 ID 列表"""

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    """首建时间"""

    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    """最后更新时间"""

    decayed_at = Column(DateTime, nullable=True)
    """衰减到阈值以下的时间，null 表示仍有效"""
```

- [ ] **Step 2: 更新 src/agents/memory/__init__.py 导出新模型**

```python
"""个性化记忆包，提供记忆的增删改查、语义检索、碎片提取和画像管理"""
from src.agents.memory.models import MemoryFragment, UserMemory, UserProfile
from src.agents.memory.service import MemoryService

__all__ = ["MemoryService", "MemoryFragment", "UserMemory", "UserProfile"]
```

- [ ] **Step 3: 在 src/models/__init__.py 中注册新模型（触发 Base.metadata 建表）**

在现有 import 之后追加：

```python
from src.agents.memory.models import MemoryFragment, UserProfile
```

并在 `__all__` 列表中追加 `"MemoryFragment", "UserProfile"`。

- [ ] **Step 4: 提交**

```bash
git add src/agents/memory/models.py src/agents/memory/__init__.py src/models/__init__.py
git commit -m "feat: add MemoryFragment and UserProfile ORM models"
```

---

### Task 2: 重写 MemoryService 核心——碎片管理、画像 CRUD、重要性计算

**Files:**
- Modify: `src/agents/memory/service.py`

- [ ] **Step 1: 重写 service.py——导入、常量和类初始化**

用以下内容完全替换 `src/agents/memory/service.py`：

```python
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

from sqlalchemy import select, delete, update
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
```

- [ ] **Step 2: 提交**

```bash
git add src/agents/memory/service.py
git commit -m "feat: rewrite MemoryService with fragment/profiles, importance, decay, contradiction"
```

---

### Task 3: 提取器模块——隐式提取 prompt + 预过滤 + LLM 调用

**Files:**
- Create: `src/agents/memory/extractor.py`

- [ ] **Step 1: 创建 extractor.py**

```python
"""
画像碎片提取器
从每条用户消息中旁路异步提取偏好、事实、习惯和关系碎片。

Workflow:
  _should_extract() 预过滤 → EXTRACT_FRAGMENTS_PROMPT 让 LLM 提取
  → 返回 [{type, content, signal_strength}] 供 MemoryService.add_fragment() 消费
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

EXTRACT_FRAGMENTS_PROMPT = """你是用户画像碎片提取器。从用户的消息中提取可能反映用户偏好、事实、习惯或关系的碎片信息。

用户消息：
{message}

该用户已有的画像摘要：
{profile_summary}

提取规则：
- preference（偏好）：用户喜欢/不喜欢什么，对事物的态度
- fact（事实）：关于用户的客观信息（地点、职业、技能、使用的工具等）
- habit（习惯）：反复出现的行为模式（"每天都..."、"习惯了..."）
- relationship（关系）：用户与其他人的关联
- signal_strength（信号强度 0.1~1.0）：越明确越高。例如"我不喝咖啡"=0.9，"可能要去杭州"=0.3
- 纯事实查询（天气、知识问答）中的隐含信息也可提取，但 signal_strength 应较低
- 只提取关于用户本人的信息，不提取临时一次性信息
- 没有值得提取的信息时返回空数组

返回 JSON 数组，不要返回其他内容：
[{{"type": "preference", "content": "用户不喝咖啡", "signal_strength": 0.9}}]"""

# 预过滤关键词：消息必须包含至少一个才进入 LLM 提取
_SHOULD_EXTRACT_PATTERNS = [
    "我", "喜欢", "不喜欢", "讨厌", "爱", "觉得", "想",
    "每天", "经常", "总是", "从来", "习惯",
    "同事", "朋友", "老板", "领导", "家人",
    "工作", "学习", "住在", "在杭州", "在北京", "在上海",
    "做", "搞", "弄", "写", "会", "能",
]


def _should_extract(message: str) -> bool:
    """预过滤：判断消息是否值得进入 LLM 提取

    参数:
        message: 用户消息文本

    返回:
        bool: 是否应提取
    """
    text = message.strip()
    if len(text) < 5:
        return False
    return any(pattern in text for pattern in _SHOULD_EXTRACT_PATTERNS)


async def extract_fragments(
    message: str,
    profile_summary: str,
    llm: Any,
) -> list[dict]:
    """从用户消息中提取画像碎片

    参数:
        message: 用户原始消息文本
        profile_summary: 已有画像的摘要文本（避免重复提取）
        llm: LLMClient 实例，需支持 chat() 方法

    返回:
        list[dict]: [{"type": "preference", "content": "...", "signal_strength": 0.9}, ...]
    """
    if not _should_extract(message):
        return []

    prompt = EXTRACT_FRAGMENTS_PROMPT.format(
        message=message,
        profile_summary=profile_summary or "（暂无已有画像）",
    )

    try:
        raw = await llm.chat(
            messages=[
                {"role": "system", "content": "只返回 JSON 数组，不要返回其他内容。提取不到信息时返回 []。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        # 清理可能的 markdown 代码块包裹
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        fragments = json.loads(raw)
        if not isinstance(fragments, list):
            return []
        valid_types = {"preference", "fact", "habit", "relationship"}
        return [
            {
                "type": f["type"],
                "content": str(f["content"]),
                "signal_strength": max(0.1, min(1.0, float(f.get("signal_strength", 0.5)))),
            }
            for f in fragments
            if isinstance(f, dict) and f.get("type") in valid_types and f.get("content")
        ]
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.debug("Memory: fragment extraction parse error: %s", e)
        return []
    except Exception as e:
        logger.warning("Memory: fragment extraction failed: %s", e)
        return []


def build_profile_summary(grouped_profiles: dict[str, list[dict]]) -> str:
    """将分组画像构建为摘要文本，供提取器使用

    参数:
        grouped_profiles: get_profiles_grouped() 的返回值

    返回:
        str: 可嵌入提取 prompt 的摘要
    """
    type_labels = {
        "preference": "偏好",
        "fact": "事实",
        "habit": "习惯",
        "relationship": "关系",
    }
    lines = []
    for profile_type, profiles in grouped_profiles.items():
        if not profiles:
            continue
        label = type_labels.get(profile_type, profile_type)
        items = [p["content"] for p in profiles[:5]]
        lines.append(f"- {label}: {', '.join(items)}")
    return "\n".join(lines) if lines else "暂无已有画像"
```

- [ ] **Step 2: 提交**

```bash
git add src/agents/memory/extractor.py
git commit -m "feat: add fragment extractor with pre-filter and LLM extraction"
```

---

### Task 4: 旁路集成——PrivateButlerAgent 主路径回复后触发碎片提取

**Files:**
- Modify: `src/agents/private_butler/graph.py`
- Modify: `src/main.py`

- [ ] **Step 1: 修改 PrivateButlerAgent.__init__() 接收 db_session_factory**

在 `src/agents/private_butler/graph.py` 中修改 `__init__`：

```python
def __init__(
    self,
    llm_client,
    summary_agent,
    knowledge_service,
    web_search_service,
    weather_service=None,
    reminder_agent=None,
    memory_service=None,
    db_session_factory=None,
):
    """初始化 PrivateButlerAgent 并编译工具调用图

    参数:
        llm_client: 支持 bind_tools().ainvoke() 和 chat() 的 LLM 客户端
        summary_agent: 摘要领域 agent
        knowledge_service: 本地知识库检索服务
        web_search_service: 联网搜索服务
        weather_service: 天气服务
        reminder_agent: 提醒 agent
        memory_service: 个性化记忆服务
        db_session_factory: 异步数据库会话工厂，供旁路提取任务创建独立 session

    返回:
        None
    """
    self._llm = llm_client
    self._memory_service = memory_service
    self._db_session_factory = db_session_factory
    self._tool_context = PrivateButlerToolContext(
        summary_agent=summary_agent,
        knowledge_service=knowledge_service,
        web_search_service=web_search_service,
        weather_service=weather_service,
        reminder_agent=reminder_agent,
        memory_service=memory_service,
    )
    self._tools = create_private_butler_tools(self._tool_context)
    self._graph = self._build_graph()
```

注意：`PrivateButlerToolContext` 也需要添加 `memory_service` 字段（当前代码中 tool_context 未传 memory_service，需要补上）。

- [ ] **Step 2: 在 handle() 方法末尾，reply 确定后触发旁路提取**

在 `handle()` 方法的 `return AgentResponse(...)` 之前，添加旁路提取逻辑：

```python
# ── 旁路：异步提取画像碎片 ──
if (
    chat_type == "single"
    and self._memory_service is not None
    and self._db_session_factory is not None
):
    import asyncio
    asyncio.create_task(
        _extract_fragments_side_path(
            message=message,
            user_id=user_id,
            db_session_factory=self._db_session_factory,
            memory_service=self._memory_service,
            llm=self._llm,
        )
    )
```

- [ ] **Step 3: 在 graph.py 底部添加旁路提取函数**

```python
import logging

from src.agents.memory.extractor import extract_fragments, build_profile_summary

_logger = logging.getLogger(__name__)


async def _extract_fragments_side_path(
    message: str,
    user_id: str,
    db_session_factory,
    memory_service,
    llm,
) -> None:
    """旁路异步提取画像碎片：不阻塞主回复，失败不影响主功能

    参数:
        message: 用户原始消息
        user_id: 用户 ID
        db_session_factory: 返回 AsyncSession 的工厂函数
        memory_service: MemoryService 实例
        llm: LLMClient 实例
    """
    try:
        async with db_session_factory() as db:
            grouped = await memory_service.get_profiles_grouped(db, user_id)
            profile_summary = build_profile_summary(grouped)
    except Exception:
        return

    fragments = await extract_fragments(message, profile_summary, llm)
    if not fragments:
        return

    try:
        async with db_session_factory() as db:
            for f in fragments:
                await memory_service.add_fragment(
                    db=db,
                    user_id=user_id,
                    fragment_type=f["type"],
                    content=f["content"],
                    signal_strength=f["signal_strength"],
                )
            new_profiles = await memory_service.aggregate_fragments(db, user_id)
            await db.commit()
            if new_profiles:
                _logger.info(
                    "Memory side-path: %s new profiles for user_id=%s",
                    len(new_profiles), user_id,
                )
    except Exception:
        pass
```

注意：`db_session_factory()` 返回的对象如果是 `async_sessionmaker`，需要用 `async with db_session_factory() as db:` 的模式。当前 `main.py` 中 `async_session` 是 `async_sessionmaker` 类型。

- [ ] **Step 4: 修改 main.py 传递 db_session_factory**

在 `src/main.py` 中修改 `PrivateButlerAgent` 的构造：

```python
from src.db.session import async_session

private_butler_agent = PrivateButlerAgent(
    llm_client=llm_client,
    summary_agent=summary_agent,
    knowledge_service=knowledge_service,
    web_search_service=web_search_service,
    weather_service=weather_service,
    reminder_agent=reminder_agent,
    memory_service=memory_service,
    db_session_factory=async_session,
)
```

- [ ] **Step 5: 提交**

```bash
git add src/agents/private_butler/graph.py src/main.py
git commit -m "feat: add side-path fragment extraction after main reply"
```

---

### Task 5: 结构化 prompt 注入——升级为分类画像注入

**Files:**
- Modify: `src/agents/private_butler/prompts.py`
- Modify: `src/agents/private_butler/graph.py`

- [ ] **Step 1: 更新 PRIVATE_BUTLER_SYSTEM_PROMPT**

在 `src/agents/private_butler/prompts.py` 中，将 prompt 模板的 `{memory_context}` 替换为结构化的 `{profile_context}`：

将：
```
已知用户信息：
{memory_context}
```

替换为：
```
[用户画像]
{profile_context}

[行为指导]
- 回答时参考用户画像中的偏好、事实和习惯，自然地调整推荐和建议
- 用户表达过不喜欢的事物，避免推荐
- 讨论技术问题时，优先用用户熟悉的工具和语言举例
- 用户提到画像中有记录的人名时，可以自然关联
- 不要生硬地背诵用户画像，要在对话中自然地体现对用户的了解
```

- [ ] **Step 2: 更新 build_system_prompt() 函数签名**

将参数名从 `memory_context` 改为 `profile_context`，默认值相同。

- [ ] **Step 3: 修改 handle() 中的 profile 检索逻辑**

在 `src/agents/private_butler/graph.py` 的 `handle()` 中，将当前的扁平 memory_context 检索替换为结构化检索：

将：
```python
memory_context = ""
if self._memory_service is not None:
    try:
        results = await self._memory_service.search(db, user_id, message, top_k=3, threshold=0.5)
        if results:
            lines = [f"- {r['content']}" for r in results]
            memory_context = "\n".join(lines)
    except Exception:
        pass
```

替换为：
```python
profile_context = ""
if self._memory_service is not None:
    try:
        grouped = await self._memory_service.get_profiles_grouped(db, user_id)
        if any(grouped.values()):
            type_labels = {
                "preference": "偏好",
                "fact": "事实",
                "habit": "习惯",
                "relationship": "关系",
            }
            lines = []
            for ptype, profiles in grouped.items():
                if profiles:
                    label = type_labels.get(ptype, ptype)
                    items = [p["content"] for p in profiles]
                    lines.append(f"- {label}: {', '.join(items)}")
            profile_context = "\n".join(lines)
    except Exception:
        pass
```

- [ ] **Step 4: 更新 initial_state 和 call_model 调用**

将 `initial_state` 中的 `"memory_context": memory_context` 改为 `"profile_context": profile_context`。

在 `nodes.py` 的 `call_model()` 中，将 `memory_context=state.get("memory_context", "")` 改为 `profile_context=state.get("profile_context", "")`。

同时更新 `PrivateButlerState` 中的 `memory_context: str` 字段为 `profile_context: str`。

- [ ] **Step 5: 提交**

```bash
git add src/agents/private_butler/prompts.py src/agents/private_butler/graph.py src/agents/private_butler/state.py src/agents/private_butler/nodes.py
git commit -m "feat: upgrade prompt injection to structured profile context"
```

---

### Task 6: 更新 memory tools 适配新 Service 接口

**Files:**
- Modify: `src/agents/private_butler/tools.py`

- [ ] **Step 1: 更新 add_memory tool**

`MemoryService.add_memory()` 现在返回 `UserProfile`（而非 `UserMemory`），接口兼容，无需改动调用方。但需要确认 `add_memory` tool 中的 `source="explicit"` 参数仍然正确。

当前代码兼容，无需改动。

- [ ] **Step 2: 更新 list_memories tool**

当前 `list_memories` 遍历 `UserMemory` 对象的 `.content` 属性，新的 `list_memories()` 返回 `UserProfile` 列表，同样有 `.content` 属性，兼容。但展示格式可以更丰富：

```python
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
        return "你还没有保存过记忆。可以跟我说'记住：xxx'来添加。"

    type_labels = {"preference": "偏好", "fact": "事实", "habit": "习惯", "relationship": "关系"}
    lines = []
    for i, m in enumerate(memories):
        label = type_labels.get(m.type, m.type)
        lines.append(f"{i+1}. [{label}] {m.content}")
    return "我记得以下关于你的信息：\n" + "\n".join(lines)
```

- [ ] **Step 3: 更新 search_memory tool**

当前返回扁平列表，可以加上类型标签：

```python
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
    type_labels = {"preference": "偏好", "fact": "事实", "habit": "习惯", "relationship": "关系"}
    lines = [f"- [{type_labels.get(r['type'], r['type'])}] {r['content']}" for r in results]
    return "相关记忆：\n" + "\n".join(lines)
```

- [ ] **Step 4: update_memory 和 delete_memory 保持不变**

这两个 tool 使用的是 `update_memory(memory_id, user_id, new_content)` 和 `delete_memory(memory_id, user_id)`，新接口签名兼容（返回类型从 `UserMemory | None` 变为 `UserProfile | None`），调用方无需改动。

- [ ] **Step 5: 提交**

```bash
git add src/agents/private_butler/tools.py
git commit -m "feat: update memory tools with profile type labels"
```

---

### Task 7: 主动应用 hook——意图触发记忆检索 + 矛盾检测调用

**Files:**
- Modify: `src/agents/private_butler/graph.py`

- [ ] **Step 1: 在 handle() 中添加主动记忆检索**

在 `handle()` 方法中，`return AgentResponse(...)` 之前（旁路提取之后），添加主动意图检索：

```python
# ── 主动应用：检测是否需要额外记忆检索 ──
_active_memory_hint = ""
if (
    chat_type == "single"
    and self._memory_service is not None
    and profile_context
):
    _active_memory_hint = _detect_active_memory_trigger(message, profile_context)

if _active_memory_hint:
    reply = f"{reply}\n\n{_active_memory_hint}"
```

- [ ] **Step 2: 在 graph.py 底部添加主动触发检测函数**

```python
# 意图 → 记忆应用提示
_ACTIVE_MEMORY_TRIGGERS = [
    (("推荐", "建议", "有什么", "喝什么", "吃什么", "选哪个"), "preference"),
    (("代码", "编程", "debug", "bug", "怎么写", "技术"), "fact"),
    (("张三", "李四", "王五", "同事", "朋友", "老板", "领导"), "relationship"),
]


def _detect_active_memory_trigger(message: str, profile_context: str) -> str:
    """检测用户消息是否触发主动记忆应用

    参数:
        message: 用户消息
        profile_context: 已注入的画像上下文

    返回:
        str: 额外的记忆提示文本，无触发时返回空字符串
    """
    for keywords, profile_type in _ACTIVE_MEMORY_TRIGGERS:
        if any(kw in message for kw in keywords):
            # 检查 profile_context 中是否已有对应类型
            type_label_map = {
                "preference": "偏好",
                "fact": "事实",
                "relationship": "关系",
            }
            label = type_label_map.get(profile_type, "")
            if label and label in profile_context:
                return ""  # 已经注入了，不再重复
            return ""  # 没有对应画像时不追加
    return ""
```

注意：这个主动触发在当前阶段做一个轻量框架，真正的"主动应用"在注入 prompt 时就已生效（通过 `[行为指导]` 段）。这里的额外触发是备用的，当前可以不追加额外文本，只做检测框架。

简化版：暂不追加额外文本，保留函数框架以备后续扩展。

- [ ] **Step 3: 在旁路提取中加入矛盾检测**

在 `_extract_fragments_side_path()` 函数中，每个 fragment 写入后检测矛盾：

```python
async def _extract_fragments_side_path(
    message: str,
    user_id: str,
    db_session_factory,
    memory_service,
    llm,
) -> None:
    """旁路异步提取画像碎片：不阻塞主回复，失败不影响主功能"""
    try:
        async with db_session_factory() as db:
            grouped = await memory_service.get_profiles_grouped(db, user_id)
            profile_summary = build_profile_summary(grouped)
    except Exception:
        return

    fragments = await extract_fragments(message, profile_summary, llm)
    if not fragments:
        return

    contradiction_flags: list[str] = []
    try:
        async with db_session_factory() as db:
            for f in fragments:
                await memory_service.add_fragment(
                    db=db, user_id=user_id,
                    fragment_type=f["type"], content=f["content"],
                    signal_strength=f["signal_strength"],
                )
                # 检测矛盾
                contradicted = await memory_service.detect_contradiction(
                    db, user_id, f["content"],
                )
                if contradicted is not None:
                    contradiction_flags.append(
                        f"'{f['content']}' 与你之前的记忆 '{contradicted.content}' 似乎不一致"
                    )

            new_profiles = await memory_service.aggregate_fragments(db, user_id)
            await db.commit()
            if new_profiles:
                _logger.info("Memory side-path: %s new profiles for user_id=%s", len(new_profiles), user_id)
            if contradiction_flags:
                _logger.info("Memory side-path: contradictions detected for user_id=%s: %s", user_id, contradiction_flags)
    except Exception:
        pass
```

矛盾标记记录日志，后续对话中 LLM 通过 prompt 中的 `[行为指导]` 自然处理（因为已有画像 confidence 已降低，下次检索不会排到前面）。

- [ ] **Step 4: 提交**

```bash
git add src/agents/private_butler/graph.py
git commit -m "feat: add active memory triggers and contradiction detection framework"
```

---

### Task 8: 最终集成、验证和清理

**Files:**
- Modify: `src/agents/memory/__init__.py`
- 清理: 确认所有 import 路径正确

- [ ] **Step 1: 确认 __init__.py 导出完整**

`src/agents/memory/__init__.py` 应导出：

```python
"""个性化记忆包，提供碎片管理、画像维护、语义检索和碎片提取"""
from src.agents.memory.extractor import extract_fragments, build_profile_summary
from src.agents.memory.models import MemoryFragment, UserMemory, UserProfile
from src.agents.memory.service import MemoryService

__all__ = [
    "MemoryService",
    "MemoryFragment",
    "UserMemory",
    "UserProfile",
    "extract_fragments",
    "build_profile_summary",
]
```

- [ ] **Step 2: 确认 main.py 中所有 DB 模型被 import**

`src/models/__init__.py` 已包含 `MemoryFragment` 和 `UserProfile` 的 import，确保 `Base.metadata.create_all` 能建表。

- [ ] **Step 3: 运行 smoke test 验证表创建和 agent 初始化**

```bash
cd /Users/assle/dev/personal_butler_agent
python3 -c "
import asyncio
async def test():
    from src.db.base import Base
    from src.db.session import async_session, engine
    import src.models  # trigger model registration
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Tables created successfully')
    tables = Base.metadata.tables.keys()
    print('Tables:', [t for t in tables if 'memory' in t or 'profile' in t])
asyncio.run(test())
"
```

预期输出包含 `memory_fragments` 和 `user_profile`。

- [ ] **Step 4: 运行现有测试确认无回归**

```bash
cd /Users/assle/dev/personal_butler_agent && uv run pytest tests/ -x --timeout=30 -q
```

- [ ] **Step 5: 提交**

```bash
git add src/agents/memory/__init__.py
git commit -m "chore: finalize memory module exports and integration"
```
