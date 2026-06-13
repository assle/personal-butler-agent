"""
工作空间 ORM 模型
定义团队工作空间表结构和成员角色关系。

Workflow:
1. Workspace 存储工作空间基础信息和策略
2. WorkspaceMember 绑定企业微信用户到工作空间并记录角色
3. 首次迁移时通过 default_workspace_id 创建默认工作空间
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


def _utcnow() -> datetime:
    """返回带 UTC 时区的当前时间"""
    return datetime.now(timezone.utc)


class Workspace(Base):
    """团队工作空间"""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", index=True
    )
    policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class WorkspaceMember(Base):
    """工作空间成员与角色"""

    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "open_userid",
            name="uq_workspace_member_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    open_userid: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="member"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active"
    )
    research_approved_once: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
