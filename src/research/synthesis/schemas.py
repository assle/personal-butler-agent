"""综合报告结构化 Schema"""
from typing import Literal
from pydantic import BaseModel, Field


class ClaimDraft(BaseModel):
    """待持久化报告结论"""
    key: str
    text: str
    claim_type: Literal["fact", "inference", "uncertainty", "recommendation"]
    material: bool = True
    evidence_ids: list[int] = Field(default_factory=list)


class ReportSectionDraft(BaseModel):
    """结构化报告章节"""
    heading: str
    body: str
    claim_keys: list[str] = Field(default_factory=list)


class ReportDraft(BaseModel):
    """Synthesizer 结构化报告草稿"""
    title: str
    summary: str
    sections: list[ReportSectionDraft] = Field(default_factory=list)
    claims: list[ClaimDraft] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class SynthesisValidationError(ValueError):
    """综合报告校验失败"""


def validate_report_draft(
    draft: ReportDraft,
    *,
    allowed_evidence_ids: set[int],
) -> None:
    """校验报告草稿引用的证据 ID 均在允许范围内

    参数:
        draft: 报告草稿
        allowed_evidence_ids: 允许引用的证据 ID 集合

    异常:
        SynthesisValidationError: 存在无效引用
    """
    for claim in draft.claims:
        for ev_id in claim.evidence_ids:
            if ev_id not in allowed_evidence_ids:
                raise SynthesisValidationError(
                    f"结论 {claim.key} 引用了不存在的证据 ID: {ev_id}"
                )
    claim_keys = {c.key for c in draft.claims}
    for section in draft.sections:
        for ck in section.claim_keys:
            if ck not in claim_keys:
                raise SynthesisValidationError(
                    f"章节 {section.heading} 引用了不存在的结论 key: {ck}"
                )
