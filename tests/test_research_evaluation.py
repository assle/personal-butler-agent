"""
研究评估数据模型测试
验证评估声明、证据、用例、制品和汇总模型的字段约束与创建行为。
"""
import pytest
from pydantic import ValidationError

from src.research.evaluation.schemas import (
    EvaluationArtifact,
    EvaluationCase,
    EvaluationClaim,
    EvaluationEvidence,
    EvaluationResult,
    EvaluationSummary,
)


def test_evaluation_result_has_required_fields():
    """验证 EvaluationResult 基本字段"""
    r = EvaluationResult(case_id="test-1")
    assert r.claim_topic_coverage == 0.0
    assert r.citation_validity == 1.0


def test_evaluation_claim_defaults():
    """验证 EvaluationClaim 默认值"""
    c = EvaluationClaim(text="test claim")
    assert c.material is True
    assert c.validation_status == "supported"
    assert c.evidence_ids == []


def test_evaluation_evidence_fields():
    """验证 EvaluationEvidence 字段赋值"""
    e = EvaluationEvidence(id=1, source_type="knowledge")
    assert e.id == 1
    assert e.source_type == "knowledge"


def test_evaluation_case_defaults():
    """验证 EvaluationCase 默认值和约束"""
    c = EvaluationCase(id="c1", question="test?")
    assert c.category == "comparison"
    assert c.required_claim_topics == []
    assert c.required_source_types == []
    assert c.forbidden_claims == []
    assert c.max_unsupported_material_claim_rate == 0.0
    assert c.max_cost_microunits == 500_000
    assert c.artifact is None


def test_evaluation_case_rate_bound():
    """验证 max_unsupported_material_claim_rate 必须在 [0,1] 内"""
    EvaluationCase(id="valid", question="q", max_unsupported_material_claim_rate=0.5)
    with pytest.raises(ValidationError):
        EvaluationCase(id="bad", question="q", max_unsupported_material_claim_rate=1.5)
    with pytest.raises(ValidationError):
        EvaluationCase(id="neg", question="q", max_unsupported_material_claim_rate=-0.1)


def test_evaluation_artifact_defaults():
    """验证 EvaluationArtifact 默认空集合"""
    a = EvaluationArtifact()
    assert a.claims == []
    assert a.evidence == []
    assert a.latency_ms == 0
    assert a.estimated_cost_microunits == 0


def test_evaluation_artifact_with_claims():
    """验证 EvaluationArtifact 装载声明和证据"""
    a = EvaluationArtifact(
        claims=[
            EvaluationClaim(text="c1", material=True, validation_status="supported"),
            EvaluationClaim(text="c2", material=False, validation_status="unsupported"),
        ],
        evidence=[EvaluationEvidence(id=1, source_type="web")],
        latency_ms=1500,
        estimated_cost_microunits=25000,
    )
    assert len(a.claims) == 2
    assert len(a.evidence) == 1
    assert a.latency_ms == 1500


def test_evaluation_case_with_artifact():
    """验证 EvaluationCase 可以关联制品"""
    a = EvaluationArtifact(
        claims=[EvaluationClaim(text="c1")],
        evidence=[EvaluationEvidence(id=1, source_type="knowledge")],
    )
    c = EvaluationCase(id="c2", question="q2", category="comparison", artifact=a)
    assert c.artifact is not None
    assert len(c.artifact.claims) == 1
    assert c.artifact.evidence[0].source_type == "knowledge"


def test_evaluation_summary_defaults():
    """验证 EvaluationSummary 默认值为零"""
    s = EvaluationSummary()
    assert s.case_count == 0
    assert s.mean_topic_coverage == 0.0
    assert s.mean_citation_validity == 0.0
    assert s.total_estimated_cost_microunits == 0
    assert s.mean_latency_ms == 0


# ---- Metric formula tests ----


def test_normalize_ignores_case_and_whitespace():
    """验证 _normalize 忽略大小写和多余空白"""
    from src.research.evaluation.runner import _normalize

    assert _normalize("  Hello World  ") == "hello world"
    assert _normalize("HELLO WORLD") == "hello world"


def test_coverage_empty_required_returns_one():
    """验证空 required 列表返回 1.0"""
    from src.research.evaluation.runner import _coverage

    assert _coverage([], "anything") == 1.0


def test_coverage_partial_match():
    """验证部分匹配的覆盖率"""
    from src.research.evaluation.runner import _coverage

    result = _coverage(["async", "delivery", "scalability"], "async delivery features")
    assert result == pytest.approx(2 / 3)


def test_coverage_full_match():
    """验证完全匹配的覆盖率"""
    from src.research.evaluation.runner import _coverage

    assert _coverage(["async", "delivery"], "Async delivery is important") == 1.0


def test_calculate_result_topic_coverage():
    """验证 _calculate_result 的主题覆盖率"""
    from src.research.evaluation.runner import _calculate_result

    case = EvaluationCase(
        id="tc1",
        question="test?",
        required_claim_topics=["async", "delivery"],
        artifact=EvaluationArtifact(
            claims=[
                EvaluationClaim(
                    text="async processing is key",
                    material=True,
                    validation_status="supported",
                ),
                EvaluationClaim(
                    text="delivery guarantees exist",
                    material=True,
                    validation_status="supported",
                ),
            ],
            evidence=[EvaluationEvidence(id=1, source_type="knowledge")],
        ),
    )
    result = _calculate_result(case)
    assert result.claim_topic_coverage == 1.0
    assert result.unsupported_material_claim_rate == 0.0


def test_calculate_result_citation_validity():
    """验证引用有效性计算"""
    from src.research.evaluation.runner import _calculate_result

    case = EvaluationCase(
        id="tc2",
        question="test?",
        artifact=EvaluationArtifact(
            claims=[
                EvaluationClaim(
                    text="claim one",
                    material=True,
                    validation_status="supported",
                    evidence_ids=[1],
                ),
                EvaluationClaim(
                    text="claim two",
                    material=True,
                    validation_status="supported",
                    evidence_ids=[99],
                ),
            ],
            evidence=[EvaluationEvidence(id=1, source_type="knowledge")],
        ),
    )
    result = _calculate_result(case)
    # only 1 of 2 claims has valid evidence
    assert result.citation_validity == 0.5


def test_calculate_result_unsupported_rate():
    """验证不支持的材料声明率"""
    from src.research.evaluation.runner import _calculate_result

    case = EvaluationCase(
        id="tc3",
        question="test?",
        artifact=EvaluationArtifact(
            claims=[
                EvaluationClaim(
                    text="supported one",
                    material=True,
                    validation_status="supported",
                ),
                EvaluationClaim(
                    text="unsupported one",
                    material=True,
                    validation_status="unsupported",
                ),
            ],
            evidence=[EvaluationEvidence(id=1, source_type="web")],
        ),
    )
    result = _calculate_result(case)
    assert result.unsupported_material_claim_rate == 0.5


def test_calculate_result_missing_artifact_raises():
    """验证缺少 artifact 时抛出 ValueError"""
    from src.research.evaluation.runner import _calculate_result

    case = EvaluationCase(id="bad", question="test?")
    with pytest.raises(ValueError, match="missing artifact"):
        _calculate_result(case)


def test_make_summary_empty():
    """验证空结果列表的汇总"""
    from src.research.evaluation.runner import _make_summary

    s = _make_summary([])
    assert s.case_count == 0


def test_make_summary_averages():
    """验证汇总计算各项平均值"""
    from src.research.evaluation.runner import _make_summary

    results = [
        EvaluationResult(
            case_id="a",
            claim_topic_coverage=1.0,
            citation_validity=0.8,
            unsupported_material_claim_rate=0.1,
            required_source_coverage=0.5,
            estimated_cost_microunits=1000,
            latency_ms=200,
        ),
        EvaluationResult(
            case_id="b",
            claim_topic_coverage=0.5,
            citation_validity=0.6,
            unsupported_material_claim_rate=0.2,
            required_source_coverage=1.0,
            estimated_cost_microunits=2000,
            latency_ms=400,
        ),
    ]
    s = _make_summary(results)
    assert s.case_count == 2
    assert s.mean_topic_coverage == pytest.approx(0.75)
    assert s.mean_citation_validity == pytest.approx(0.7)
    assert s.mean_unsupported_material_claim_rate == pytest.approx(0.15)
    assert s.mean_required_source_coverage == pytest.approx(0.75)
    assert s.total_estimated_cost_microunits == 3000
    assert s.mean_latency_ms == 300


def test_run_offline_integration(tmp_path):
    """验证 EvaluationRunner 端到端运行"""
    from src.research.evaluation.runner import EvaluationRunner

    cases = [
        {
            "id": "int-1",
            "question": "Compare X and Y",
            "required_claim_topics": ["topic_a"],
            "artifact": {
                "claims": [
                    {
                        "text": "topic_a is covered",
                        "material": True,
                        "validation_status": "supported",
                    }
                ],
                "evidence": [{"id": 1, "source_type": "web"}],
                "latency_ms": 100,
                "estimated_cost_microunits": 5000,
            },
        },
    ]
    path = tmp_path / "cases.json"
    path.write_text(__import__("json").dumps(cases))
    runner = EvaluationRunner()
    results = runner.run_offline(path)
    assert len(results) == 1
    assert results[0].claim_topic_coverage == 1.0
    assert results[0].estimated_cost_microunits == 5000


def test_dataset_has_24_cases():
    """验证评估数据集包含 24 个用例"""
    import json
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "research_eval_cases.json"
    data = json.loads(path.read_text())
    assert len(data) == 24, f"Expected 24 cases, got {len(data)}"


def test_dataset_categories_are_valid():
    """验证所有用例的 category 是已定义的分类"""
    import json
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "research_eval_cases.json"
    data = json.loads(path.read_text())
    valid_categories = {
        "comparison", "performance", "architecture", "factual",
        "howto", "troubleshooting", "design", "security",
        "best-practice", "migration", "research", "data-modeling",
    }
    for case in data:
        assert case["category"] in valid_categories, (
            f"Case {case['id']} has invalid category {case['category']}"
        )


def test_dataset_all_have_artifacts():
    """验证所有用例都包含 artifact"""
    import json
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "research_eval_cases.json"
    data = json.loads(path.read_text())
    for case in data:
        assert "artifact" in case, f"Case {case['id']} missing artifact"
        assert "claims" in case["artifact"], f"Case {case['id']} artifact missing claims"
        assert "evidence" in case["artifact"], f"Case {case['id']} artifact missing evidence"


def test_dataset_run_offline():
    """验证数据集可通过 EvaluationRunner 运行"""
    from pathlib import Path
    from src.research.evaluation.runner import EvaluationRunner

    path = Path(__file__).parent / "fixtures" / "research_eval_cases.json"
    runner = EvaluationRunner()
    results = runner.run_offline(path)
    assert len(results) == 24
    for r in results:
        assert r.case_id.startswith(tuple(
            "comparison performance architecture factual howto "
            "troubleshooting design security best-practice migration "
            "research data-modeling".split()
        ))


def test_cli_output_format(tmp_path):
    """验证 CLI 输出包含 generated_at, summary 和 results"""
    import json
    from pathlib import Path
    from src.cli.evaluate_research import run as cli_run
    import sys

    fixtures = Path(__file__).parent / "fixtures" / "research_eval_cases.json"
    out = tmp_path / "eval_output.json"

    old_argv = sys.argv
    try:
        sys.argv = [
            "butler-evaluate-research",
            "--cases", str(fixtures),
            "--offline",
            "--output", str(out),
        ]
        cli_run()
    finally:
        sys.argv = old_argv

    data = json.loads(out.read_text())
    assert "generated_at" in data
    assert "provenance" in data
    assert data["provenance"]["evaluation_mode"] == "offline_fixture"
    assert data["provenance"]["external_calls"] is False
    assert data["provenance"]["pipeline_execution"] is False
    assert "summary" in data
    assert "results" in data
    assert len(data["results"]) == 24
    assert "mean_topic_coverage" in data["summary"]
    assert data["summary"]["case_count"] == 24


def test_evaluation_provenance_is_explicit():
    """验证离线评测不会被误认为真实模型运行"""
    from src.research.evaluation.schemas import EvaluationProvenance
    provenance = EvaluationProvenance(
        artifact_source="tests/fixtures/research_eval_cases.json"
    )
    assert provenance.evaluation_mode == "offline_fixture"
    assert provenance.external_calls is False
    assert provenance.pipeline_execution is False
