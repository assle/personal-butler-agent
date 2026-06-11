"""
群投票 ORM 模型
存储群聊投票及其选项和成员投票记录。

Workflow:
1. PollAgent.create_poll_node 解析群聊 @bot 投票请求后写入 Poll
2. PollAgent.cast_vote_node 记录或更新 PollVote（一人一票 UPSERT）
3. PollAgent.view_results_node/end_poll_node 查询 PollVote 聚合统计并格式化展示
4. 到期时 SchedulerManager 回调查询结果并推送
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint

from src.db.base import Base


class Poll(Base):
    """群投票表"""

    __tablename__ = "polls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    chat_id = Column(String(256), nullable=False, index=True)
    """群聊 ID，对应企业微信回调 chatid"""

    creator_user_id = Column(String(256), nullable=False)
    """投票创建者 userid"""

    title = Column(String(512), nullable=False)
    """投票标题，例如'周末团建去哪？'"""

    options = Column(JSON, nullable=False)
    """选项列表，例如 ["香山", "故宫", "颐和园"]"""

    end_time = Column(DateTime, nullable=True)
    """到期时间，空表示手动结束"""

    status = Column(String(32), nullable=False, default="active")
    """状态：active / ended"""

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    """创建时间"""


class PollVote(Base):
    """投票记录表，一人一票"""

    __tablename__ = "poll_votes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    poll_id = Column(Integer, ForeignKey("polls.id"), nullable=False, index=True)
    """关联 Poll.id"""

    user_id = Column(String(256), nullable=False)
    """投票人 userid"""

    option_index = Column(Integer, nullable=False)
    """选项序号，0-based"""

    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    """最后投票或改票时间"""

    __table_args__ = (UniqueConstraint("poll_id", "user_id"),)
    """同一投票中每人只能投一次票，改票通过 UPSERT 覆盖"""
