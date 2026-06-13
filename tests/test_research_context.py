"""上下文构建器测试"""
from src.research.reliability.context import ResearchContextBuilder

def test_supervisor_context_excludes_full_source_bodies():
    ctx = ResearchContextBuilder().for_supervisor("R1", "test")
    d = ctx.model_dump_json()
    assert "full_page_body" not in d

def test_reviewer_context_contains_only_bound_evidence():
    ctx = ResearchContextBuilder().for_reviewer(1, [{"key": "c1"}], {"c1": [{"id": 1}]})
    assert ctx.report_id == 1
    assert len(ctx.claims) == 1
    assert "c1" in ctx.bound_evidence
