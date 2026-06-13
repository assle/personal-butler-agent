"""
研究任务共享数据结构
定义任务、投递和质量状态，供服务、Worker 和私聊入口共享。
"""
from dataclasses import dataclass
from enum import StrEnum


class ResearchTaskStatus(StrEnum):
    """研究主任务状态"""

    SUBMITTED = "submitted"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    SYNTHESIZING = "synthesizing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    RETRYING = "retrying"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchStepStatus(StrEnum):
    """研究步骤状态"""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchDeliveryStatus(StrEnum):
    """研究报告投递状态"""

    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"


ACTIVE_RESEARCH_STATUSES: set[str] = {
    ResearchTaskStatus.SUBMITTED.value,
    ResearchTaskStatus.PLANNING.value,
    ResearchTaskStatus.AWAITING_APPROVAL.value,
    ResearchTaskStatus.RUNNING.value,
    ResearchTaskStatus.SYNTHESIZING.value,
    ResearchTaskStatus.VALIDATING.value,
    ResearchTaskStatus.RETRYING.value,
}


@dataclass(frozen=True)
class ResearchReportSnapshot:
    """供投递层使用的报告快照"""

    task_id: str
    requester_open_userid: str
    question: str
    summary: str
    body: str
    quality_status: str
    workspace_id: str
