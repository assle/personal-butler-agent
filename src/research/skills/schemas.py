"""研究 Skill 清单 Schema"""
from pydantic import BaseModel

class ResearchSkillManifest(BaseModel):
    name: str
    version: str
    description: str
    applies_to: list[str]
    allowed_tools: list[str]
    evidence_policy: str
    report_schema: str
    reviewer_policy: str
