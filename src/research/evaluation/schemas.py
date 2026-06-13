from pydantic import BaseModel

class EvaluationResult(BaseModel):
    case_id: str
    claim_topic_coverage: float = 0.0
    citation_validity: float = 1.0
    unsupported_material_claim_rate: float = 0.0
    required_source_coverage: float = 1.0
    estimated_cost_microunits: int = 0
    latency_ms: int = 0
