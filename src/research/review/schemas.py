"""
引用审查结构化 Schema
定义引用审查的输入输出数据结构，用于独立引用审查阶段
"""
from typing import Literal
from pydantic import BaseModel, Field


class ReviewFindingDraft(BaseModel):
    """引用审查发现"""
    finding_type: Literal[
        "source_missing", "unsupported", "partial_support",
        "citation_mismatch", "conflict", "missing_citation",
    ]
    severity: Literal["info", "warning", "error"] = "warning"
    evidence_id: int | None = None
    message: str


class ClaimReview(BaseModel):
    """单条结论审查结果"""
    claim_key: str
    status: Literal["supported", "partial", "unsupported", "conflicted"]
    findings: list[ReviewFindingDraft] = Field(default_factory=list)


class CitationReview(BaseModel):
    """报告引用审查结果"""
    decision: Literal["pass", "repair", "fail"]
    claim_reviews: list[ClaimReview]
    missing_material_claims: list[str] = Field(default_factory=list)
