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
