"""
离线评估运行器
从 JSON 文件加载用例，计算声明覆盖率、引用有效性、不支持率等质量指标。

Workflow:
1. 读取并反序列化 EvaluationCase 列表（含 EvaluationArtifact）
2. 对每个用例调用 _calculate_result 计算指标
3. 可选汇总为 EvaluationSummary
"""
import json
from pathlib import Path
from typing import Any

from src.research.evaluation.schemas import (
    EvaluationArtifact,
    EvaluationCase,
    EvaluationEvidence,
    EvaluationResult,
    EvaluationSummary,
)


def _normalize(text: str) -> str:
    """归一化文本：小写、合并空白"""
    return " ".join(text.casefold().split())


def _coverage(required: list[str], corpus: str) -> float:
    """计算必要主题在语料中的覆盖率

    参数:
        required: 必需主题列表
        corpus: 检索语料

    返回:
        float: [0,1] 覆盖率，空列表时返回 1.0
    """
    if not required:
        return 1.0
    normalized = _normalize(corpus)
    hits = sum(_normalize(item) in normalized for item in required)
    return hits / len(required)


def _build_case(data: dict[str, Any]) -> EvaluationCase:
    """从字典构建 EvaluationCase，含可选的 artifact 反序列化

    参数:
        data: 字典数据

    返回:
        EvaluationCase: 解析后的用例对象
    """
    raw = dict(data)
    art = raw.pop("artifact", None)
    case = EvaluationCase(**raw)
    if art is not None:
        evidence_list = [EvaluationEvidence(**e) for e in art.get("evidence", [])]
        from src.research.evaluation.schemas import EvaluationClaim

        claims_list = [EvaluationClaim(**c) for c in art.get("claims", [])]
        case.artifact = EvaluationArtifact(
            claims=claims_list,
            evidence=evidence_list,
            latency_ms=art.get("latency_ms", 0),
            estimated_cost_microunits=art.get("estimated_cost_microunits", 0),
        )
    return case


def _calculate_result(case: EvaluationCase) -> EvaluationResult:
    """计算单个用例的评估指标

    参数:
        case: EvaluationCase（需包含 artifact）

    返回:
        EvaluationResult: 评估结果
    """
    artifact = case.artifact
    if artifact is None:
        raise ValueError(f"Case {case.id} missing artifact")

    material = [c for c in artifact.claims if c.material]
    supported_text = " ".join(
        c.text for c in material if c.validation_status == "supported"
    )

    topic_coverage = _coverage(case.required_claim_topics, supported_text)

    evidence_ids = {e.id for e in artifact.evidence}
    valid_citations = sum(
        1
        for c in material
        if c.validation_status == "supported"
        and any(eid in evidence_ids for eid in c.evidence_ids)
    )
    citation_validity = valid_citations / len(material) if material else 1.0

    unsupported = sum(
        1 for c in material if c.validation_status == "unsupported"
    )
    unsupported_rate = unsupported / len(material) if material else 0.0

    all_text = " ".join(c.text for c in artifact.claims)
    source_types_present = {e.source_type for e in artifact.evidence}
    source_coverage = (
        sum(
            1 for st in case.required_source_types if st in source_types_present
        )
        / len(case.required_source_types)
        if case.required_source_types
        else 1.0
    )

    return EvaluationResult(
        case_id=case.id,
        claim_topic_coverage=topic_coverage,
        citation_validity=citation_validity,
        unsupported_material_claim_rate=unsupported_rate,
        required_source_coverage=source_coverage,
        estimated_cost_microunits=artifact.estimated_cost_microunits,
        latency_ms=artifact.latency_ms,
    )


def _make_summary(results: list[EvaluationResult]) -> EvaluationSummary:
    """汇总多个用例结果

    参数:
        results: EvaluationResult 列表

    返回:
        EvaluationSummary: 汇总指标
    """
    if not results:
        return EvaluationSummary()
    n = len(results)
    return EvaluationSummary(
        case_count=n,
        mean_topic_coverage=sum(r.claim_topic_coverage for r in results) / n,
        mean_citation_validity=sum(r.citation_validity for r in results) / n,
        mean_unsupported_material_claim_rate=sum(
            r.unsupported_material_claim_rate for r in results
        )
        / n,
        mean_required_source_coverage=sum(
            r.required_source_coverage for r in results
        )
        / n,
        total_estimated_cost_microunits=sum(
            r.estimated_cost_microunits for r in results
        ),
        mean_latency_ms=int(sum(r.latency_ms for r in results) / n),
    )


class EvaluationRunner:
    """评估运行器：加载用例、计算指标、输出结果和汇总"""

    def run_offline(self, cases_path: Path) -> list[EvaluationResult]:
        """离线执行评估

        参数:
            cases_path: JSON 用例文件路径

        返回:
            list[EvaluationResult]: 各用例评估结果
        """
        raw = json.loads(cases_path.read_text())
        results = []
        for item in raw:
            case = _build_case(item)
            results.append(_calculate_result(case))
        return results

    def run_offline_with_summary(
        self, cases_path: Path
    ) -> tuple[list[EvaluationResult], EvaluationSummary]:
        """离线执行评估并返回汇总

        参数:
            cases_path: JSON 用例文件路径

        返回:
            tuple: (结果列表, 汇总)
        """
        results = self.run_offline(cases_path)
        return results, _make_summary(results)
