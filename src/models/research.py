"""
异步研究任务 ORM 模型
持久化任务、报告、独立投递状态、群知识授权和企微用户身份映射。

Workflow:
1. 私聊提交写入 ResearchTask
2. Worker 生成 ResearchReport
3. 独立投递任务更新 ResearchDelivery
4. WeComUserBinding 缓存 open_userid 到 userid 的受控转换
5. UserGroupAccess 为后续群知识库检索提供管理员授权
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


def _utcnow() -> datetime:
    """返回带 UTC 时区的当前时间"""
    return datetime.now(timezone.utc)


class ResearchTask(Base):
    """研究任务主表"""

    __tablename__ = "research_tasks"
    __table_args__ = (
        Index("ix_research_tasks_user_status", "requester_open_userid", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_msgid: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    requester_open_userid: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    research_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="foundation"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="submitted", index=True
    )
    access_scope: Mapped[dict] = mapped_column(JSON, nullable=False)
    max_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class ResearchReport(Base):
    """研究报告版本表"""

    __tablename__ = "research_reports"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_research_report_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class ResearchDelivery(Base):
    """研究报告主动私聊投递状态"""

    __tablename__ = "research_deliveries"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    recipient_userid: Mapped[str | None] = mapped_column(String(256), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wecom_msgid: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class UserGroupAccess(Base):
    """管理员维护的用户群知识库授权"""

    __tablename__ = "user_group_access"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_user_group_access"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    group_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class WeComUserBinding(Base):
    """智能机器人 open_userid 到自建应用 userid 的映射"""

    __tablename__ = "wecom_user_bindings"

    open_userid: Mapped[str] = mapped_column(String(256), primary_key=True)
    userid: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active"
    )
    converted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
