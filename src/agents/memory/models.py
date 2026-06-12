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
    """提取出的原始碎片文本，如"用户在杭州工作" """

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
    """画像条目文本，如"用户不喝咖啡，偏好喝茶" """

    confidence = Column(Float, nullable=False, default=0.6)
    """置信度 0.0~1.0，碎片池中出现次数折算"""

    importance = Column(Float, nullable=False, default=0.5)
    """重要性 0.0~1.0，来源权重×0.4 + 置信度×0.4 + 信号强度×0.2"""

    source = Column(String(32), nullable=False, default="implicit")
    """来源：explicit（用户说"记住"）/ implicit（隐式提取）"""

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
