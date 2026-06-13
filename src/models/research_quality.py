"""
研究质量 ORM 模型
持久化报告结论、证据引用绑定和审查发现
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResearchClaim(Base):
    """研究报告中的可验证结论"""

    __tablename__ = "research_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    report_id: Mapped[int] = mapped_column(
        ForeignKey("research_reports.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    claim_key: Mapped[str] = mapped_column(String(128), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)  # fact|inference|uncertainty|recommendation
    material: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )


class ResearchClaimEvidence(Base):
    """结论与证据支持关系"""

    __tablename__ = "research_claim_evidence"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "claim_id", "evidence_id",
            name="uq_research_claim_evidence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("research_claims.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("research_evidence.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    support_level: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )  # supports|partial|contradicts
    rationale: Mapped[str] = mapped_column(Text, nullable=False)


class ResearchReviewFinding(Base):
    """引用审查发现"""

    __tablename__ = "research_review_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    report_id: Mapped[int] = mapped_column(
        ForeignKey("research_reports.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_claims.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_evidence.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    finding_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # info|warning|error
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
