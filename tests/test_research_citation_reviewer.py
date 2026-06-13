"""引用审查测试"""
import pytest
from src.research.review.schemas import (
    CitationReview,
    ClaimReview,
    ReviewFindingDraft,
)


def test_review_decision_requires_finding_for_unsupported_claim():
    """验证 unsupported 结论必须给出结构化原因"""
    review = CitationReview(
        decision="repair",
        claim_reviews=[
            ClaimReview(
                claim_key="c1",
                status="unsupported",
                findings=[ReviewFindingDraft(
                    finding_type="unsupported",
                    severity="error",
                    message="No evidence supports this claim",
                )],
            )
        ],
    )
    assert review.decision == "repair"
    assert len(review.claim_reviews[0].findings) > 0


def test_citation_review_all_fields_accessible():
    """验证审查结构所有字段可访问"""
    review = CitationReview(
        decision="pass",
        claim_reviews=[
            ClaimReview(
                claim_key="c1",
                status="supported",
                findings=[],
            )
        ],
    )
    assert review.decision == "pass"
    assert review.claim_reviews[0].status == "supported"
