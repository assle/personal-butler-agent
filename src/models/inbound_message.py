"""
智能机器人入站消息持久化模型
用于 URL 回调模式下先落库再处理，避免回调重试或进程崩溃造成消息接收状态不可追踪

Workflow:
1. 回调路由解析出消息体后按 msgid 写入 inbound_messages
2. msgid 唯一约束保证企业微信重试不会重复处理
3. 后台处理任务根据 status 标记 pending/processing/processed/failed
4. 运维可查询 failed/pending 消息，为后续补偿重放预留入口
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from src.db.base import Base


class InboundMessage(Base):
    """智能机器人入站消息表"""

    __tablename__ = "inbound_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    msgid = Column(String(128), nullable=False, unique=True, index=True)
    """企业微信消息唯一 ID，用于幂等去重"""

    source = Column(String(64), nullable=False, default="aibot_callback")
    """消息来源，当前为 aibot_callback"""

    status = Column(String(32), nullable=False, default="pending", index=True)
    """处理状态：pending/processing/processed/failed"""

    payload_json = Column(Text, nullable=False)
    """原始消息 JSON 字符串"""

    response_url = Column(Text, nullable=True)
    """企业微信提供的临时回复 URL"""

    attempts = Column(Integer, nullable=False, default=0)
    """处理尝试次数"""

    error = Column(Text, nullable=True)
    """最后一次处理失败的错误信息"""

    received_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    """收到回调并落库的时间"""

    processed_at = Column(DateTime(timezone=True), nullable=True)
    """处理成功或最终失败的时间"""
