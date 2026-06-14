"""
研究质量评估数据模型
定义评估用例、声明、证据、制品和汇总的 Pydantic 模型，
以及前向引用所需的延迟类型注解。

Workflow:
1. 定义评估用例 (EvaluationCase) 及其依赖的变量和约束
2. 制品 (EvaluationArtifact) 装载声明和证据供指标计算
3. 评估汇总 (EvaluationSummary) 聚合所有用例的指标
"""
from pydantic import BaseModel, Field


class EvaluationClaim(BaseModel):
    """评估声明：被评测模型/系统生成的单个事实性陈述"""

    text: str
    material: bool = True
    validation_status: str = "supported"  # supported|partial|unsupported
    evidence_ids: list[int] = Field(default_factory=list)


class EvaluationEvidence(BaseModel):
    """评估证据：支撑声明的原始来源记录"""

    id: int
    source_type: str  # knowledge|web|web_page


class EvaluationCase(BaseModel):
    """评估用例：包含问题、强制/禁止条件、质量阈值"""

    id: str
    question: str
    category: str = "comparison"
    required_claim_topics: list[str] = Field(default_factory=list)
    required_source_types: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    max_unsupported_material_claim_rate: float = Field(default=0.0, ge=0, le=1)
    max_cost_microunits: int = Field(default=500_000, ge=0)
    artifact: "EvaluationArtifact | None" = None


class EvaluationArtifact(BaseModel):
    """评估制品：声明、证据、延迟和成本的集合"""

    claims: list[EvaluationClaim] = Field(default_factory=list)
    evidence: list[EvaluationEvidence] = Field(default_factory=list)
    latency_ms: int = 0
    estimated_cost_microunits: int = 0


class EvaluationResult(BaseModel):
    """单用例评估结果"""

    case_id: str
    claim_topic_coverage: float = 0.0
    citation_validity: float = 1.0
    unsupported_material_claim_rate: float = 0.0
    required_source_coverage: float = 1.0
    estimated_cost_microunits: int = 0
    latency_ms: int = 0


class EvaluationProvenance(BaseModel):
    """离线评测来源说明，防止把 fixture 数据描述为在线实测"""

    evaluation_mode: str = "offline_fixture"
    artifact_source: str
    external_calls: bool = False
    pipeline_execution: bool = False
    latency_source: str = "fixture_input"
    cost_source: str = "fixture_input"


class EvaluationSummary(BaseModel):
    """全面评估汇总指标"""

    case_count: int = 0
    mean_topic_coverage: float = 0.0
    mean_citation_validity: float = 0.0
    mean_unsupported_material_claim_rate: float = 0.0
    mean_required_source_coverage: float = 0.0
    total_estimated_cost_microunits: int = 0
    mean_latency_ms: int = 0
