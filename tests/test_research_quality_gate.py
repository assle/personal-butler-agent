"""质量门测试"""
from src.research.review.service import _apply_quality_gate, QualityDecision
from src.research.review.schemas import CitationReview, ClaimReview


class FakeClaim:
    def __init__(self, claim_key, material=True, validation_status="supported"):
        self.claim_key = claim_key
        self.material = material
        self.validation_status = validation_status


def test_quality_gate_passes_when_all_supported():
    claims = [FakeClaim("c1"), FakeClaim("c2")]
    review = CitationReview(decision="pass", claim_reviews=[])
    result = _apply_quality_gate(claims, review)
    assert result.outcome == "pass"


def test_quality_gate_repairs_when_material_claim_unsupported():
    claims = [FakeClaim("c1", validation_status="unsupported")]
    review = CitationReview(decision="pass", claim_reviews=[])
    result = _apply_quality_gate(claims, review)
    assert result.outcome == "repair"
    assert "c1" in result.unsupported_claim_keys


def test_quality_gate_fails_on_reviewer_fail():
    claims = [FakeClaim("c1")]
    review = CitationReview(decision="fail", claim_reviews=[])
    result = _apply_quality_gate(claims, review)
    assert result.outcome == "fail"
