"""Supervisor 规划接口"""
from dataclasses import dataclass
from src.research.planning.schemas import PlanDraft


@dataclass(frozen=True)
class TaskSnapshot:
    """规划所需任务快照"""
    task_id: str
    workspace_id: str
    question: str
    user_id: str
    member_id: int = 0
    role: str = "member"
    research_approved_once: bool = False


@dataclass(frozen=True)
class PlanningResult:
    """规划执行结果"""
    task_id: str
    plan: PlanDraft
    requires_approval: bool
    approval_reason: str = ""
