"""
研究任务共享数据结构
定义任务、投递和质量状态，供服务、Worker 和私聊入口共享。
"""
from dataclasses import dataclass
from enum import StrEnum


class ResearchTaskStatus(StrEnum):
    """研究任务状态"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class ResearchDeliveryStatus(StrEnum):
    """研究报告投递状态"""

    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"


ACTIVE_RESEARCH_STATUSES = {
    ResearchTaskStatus.QUEUED.value,
    ResearchTaskStatus.RUNNING.value,
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
