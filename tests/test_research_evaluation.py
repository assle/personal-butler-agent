def test_evaluation_result_has_required_fields():
    from src.research.evaluation.schemas import EvaluationResult
    r = EvaluationResult(case_id="test-1")
    assert r.claim_topic_coverage == 0.0
    assert r.citation_validity == 1.0
