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
