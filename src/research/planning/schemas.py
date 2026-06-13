"""研究计划草案 Schema"""
from pydantic import BaseModel, Field


class StepDraft(BaseModel):
    """待持久化的研究步骤"""

    key: str
    kind: str
    tool_name: str
    input_payload: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    max_attempts: int = Field(default=3, ge=1, le=5)


class PlanDraft(BaseModel):
    """Supervisor 输出的结构化研究计划"""

    objective: str
    completion_criteria: list[str]
    estimated_tokens: int = Field(ge=0)
    estimated_cost_microunits: int = Field(ge=0)
    steps: list[StepDraft]
