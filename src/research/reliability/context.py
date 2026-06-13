"""研究阶段上下文构建器"""
from pydantic import BaseModel

class SupervisorContext(BaseModel):
    task_id: str
    objective: str
    plan_summary: str = ""
    step_states: list[dict] = []
    evidence_coverage: list[dict] = []
    remaining_budget: dict = {}

class SpecialistContext(BaseModel):
    task_id: str
    step_id: str
    subquestion: str
    prior_evidence_summaries: list[dict] = []

class ReviewerContext(BaseModel):
    report_id: int = 0
    claims: list[dict] = []
    bound_evidence: dict[str, list[dict]] = {}

class ResearchContextBuilder:
    def for_supervisor(self, task_id: str, objective: str, **kwargs) -> SupervisorContext:
        return SupervisorContext(task_id=task_id, objective=objective, **kwargs)

    def for_specialist(self, task_id: str, step_id: str, subquestion: str, **kwargs) -> SpecialistContext:
        return SpecialistContext(task_id=task_id, step_id=step_id, subquestion=subquestion, **kwargs)

    def for_reviewer(self, report_id: int, claims: list[dict], evidence: dict, **kwargs) -> ReviewerContext:
        return ReviewerContext(report_id=report_id, claims=claims, bound_evidence=evidence, **kwargs)
