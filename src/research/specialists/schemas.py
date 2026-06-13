"""Specialist 共享 Schema"""
from pydantic import BaseModel, Field
from src.research.evidence import EvidenceInput


class RetrievalResult(BaseModel):
    """检索 Specialist 结构化结果"""
    summary: str
    evidence: list[EvidenceInput] = Field(default_factory=list)
    follow_up_queries: list[str] = Field(default_factory=list)
    degraded: bool = False
    degradation_reason: str | None = None
