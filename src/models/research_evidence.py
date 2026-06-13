"""
研究证据 ORM 模型
持久化从知识库和网页检索到的可追溯研究证据

Workflow:
1. 研究执行步骤产生 EvidenceInput → ResearchEvidenceService.store() 持久化
2. SHA-256 去重保证同工作空间相同来源内容只存一份
3. 按 task_id 查询汇总提供给报告合成阶段
"""
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
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


class ResearchEvidence(Base):
    """可追溯研究证据"""

    __tablename__ = "research_evidence"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "content_hash",
            name="uq_research_evidence_hash",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    step_id: Mapped[str] = mapped_column(
        ForeignKey("research_steps.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(512), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
