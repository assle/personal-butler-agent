"""
企业微信群聊消息持久化模型
被动收集群聊中所有消息，支持按群 ID 查询最近消息和自动清理旧数据

在总流程中的位置:
  群聊消息回调 → receive_message → GroupMessage.save(chat_id, user_id, content, create_time)
  触发总结时 → GroupMessage.get_recent(chat_id, limit=50) → LLM 总结
  每次写入后 → GroupMessage.cleanup(chat_id, keep=200) 防止数据膨胀
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy import delete, desc, select

from src.db.base import Base


class GroupMessage(Base):
    """群聊消息模型，按 chat_id 分组存储，每群保留最近 200 条"""

    __tablename__ = "group_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    chat_id = Column(String(256), nullable=False, index=True)
    """群聊唯一标识，来自企业微信回调的 ChatId 元素"""

    user_id = Column(String(256), nullable=False)
    """发送者 OpenID，来自企业微信回调的 FromUserName"""

    content = Column(Text, nullable=False)
    """消息文本内容"""

    create_time = Column(Integer, nullable=False)
    """消息创建时间戳（企业微信的 CreateTime，Unix 秒）"""

    stored_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    """记录写入本地数据库的时间"""

    @classmethod
    async def save(cls, db, chat_id: str, user_id: str, content: str, create_time: int):
        """保存一条群聊消息并立即刷写

        参数:
            db: SQLAlchemy 异步会话
            chat_id: 群聊 ID
            user_id: 发送者标识
            content: 消息文本内容
            create_time: 消息原始时间戳

        返回:
            GroupMessage: 已持久化的消息对象
        """
        msg = cls(
            chat_id=chat_id,
            user_id=user_id,
            content=content,
            create_time=create_time,
        )
        db.add(msg)
        await db.flush()
        return msg

    @classmethod
    async def get_recent(cls, db, chat_id: str, limit: int = 50):
        """获取指定群聊最近 N 条消息，按时间升序排列

        参数:
            db: SQLAlchemy 异步会话
            chat_id: 群聊 ID
            limit: 返回最近的消息条数（默认 50）

        返回:
            list[GroupMessage]: 按时间升序排列的消息列表
        """
        stmt = (
            select(cls)
            .where(cls.chat_id == chat_id)
            .order_by(desc(cls.create_time))
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(reversed(result.scalars().all()))

    @classmethod
    async def cleanup(cls, db, chat_id: str, keep: int = 200):
        """清理旧消息，每个群聊仅保留最近 N 条

        参数:
            db: SQLAlchemy 异步会话
            chat_id: 群聊 ID
            keep: 保留的消息条数（默认 200）
        """
        subq = (
            select(cls.id)
            .where(cls.chat_id == chat_id)
            .order_by(desc(cls.create_time))
            .offset(keep)
        )
        stmt = delete(cls).where(
            cls.chat_id == chat_id,
            cls.id.in_(subq),
        )
        await db.execute(stmt)
        await db.flush()
