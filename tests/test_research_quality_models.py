"""研究质量模型测试"""
from src.db.base import Base


def test_quality_tables_are_registered():
    """验证结论、证据绑定和审查结果表已注册"""
    assert {
        "research_claims",
        "research_claim_evidence",
        "research_review_findings",
    } <= set(Base.metadata.tables)


def test_claim_evidence_binding_is_unique():
    """验证同一结论与证据不能重复绑定"""
    table = Base.metadata.tables["research_claim_evidence"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if hasattr(constraint, "columns")
    }
    assert ("workspace_id", "claim_id", "evidence_id") in unique_columns
