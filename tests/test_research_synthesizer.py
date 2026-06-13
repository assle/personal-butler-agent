"""综合报告测试"""
import pytest
from src.research.synthesis.schemas import (
    ClaimDraft,
    ReportDraft,
    ReportSectionDraft,
    SynthesisValidationError,
    validate_report_draft,
)


def test_report_draft_rejects_unknown_evidence_id():
    """验证草稿不能引用输入证据集之外的 ID"""
    draft = ReportDraft(
        title="Report",
        summary="Summary",
        sections=[],
        claims=[
            ClaimDraft(
                key="c1",
                text="Unsupported",
                claim_type="fact",
                material=True,
                evidence_ids=[999],
            )
        ],
    )
    with pytest.raises(SynthesisValidationError):
        validate_report_draft(draft, allowed_evidence_ids={1, 2})


def test_validate_report_draft_accepts_valid_draft():
    """验证合法草稿通过校验"""
    draft = ReportDraft(
        title="Test",
        summary="Summary",
        sections=[ReportSectionDraft(heading="S1", body="text", claim_keys=["c1"])],
        claims=[ClaimDraft(key="c1", text="claim", claim_type="fact", evidence_ids=[1])],
    )
    validate_report_draft(draft, allowed_evidence_ids={1, 2, 3})


def test_validate_rejects_missing_claim_key_in_section():
    """验证章节引用了不存在的结论 key"""
    draft = ReportDraft(
        title="Test", summary="S",
        sections=[ReportSectionDraft(heading="S1", body="x", claim_keys=["nonexistent"])],
        claims=[],
    )
    with pytest.raises(SynthesisValidationError):
        validate_report_draft(draft, allowed_evidence_ids=set())
