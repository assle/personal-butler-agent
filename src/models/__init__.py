"""ORM 模型包，包含 SQLite 数据表映射"""
from src.models.group_message import GroupMessage
from src.models.conversation import ConversationMessage, ConversationSummary
from src.models.knowledge import (
    KnowledgeChunk,
    KnowledgeChunkEmbedding,
    KnowledgeDocument,
)
from src.models.inbound_message import InboundMessage
from src.models.poll import Poll, PollVote
from src.models.workspace import Workspace, WorkspaceMember
from src.models.group_webhook import GroupWebhook
from src.models.reminder import Reminder, ReminderRun
from src.agents.memory.models import MemoryFragment, UserMemory, UserProfile
from src.models.research import (
    ResearchDelivery,
    ResearchReport,
    ResearchTask,
    UserGroupAccess,
    WeComUserBinding,
)
from src.models.research_evidence import ResearchEvidence
from src.models.research_quality import (
    ResearchClaim,
    ResearchClaimEvidence,
    ResearchReviewFinding,
)
from src.models.research_execution import (
    ResearchApproval,
    ResearchEvent,
    ResearchPlan,
    ResearchStep,
    ResearchStepDependency,
    ResearchUsage,
)

__all__ = [
    "GroupMessage",
    "ConversationMessage",
    "ConversationSummary",
    "KnowledgeDocument",
    "KnowledgeChunk",
    "KnowledgeChunkEmbedding",
    "InboundMessage",
    "Poll",
    "PollVote",
    "GroupWebhook",
    "Reminder",
    "ReminderRun",
    "MemoryFragment",
    "UserMemory",
    "UserProfile",
    "ResearchTask",
    "ResearchReport",
    "ResearchDelivery",
    "ResearchEvidence",
    "UserGroupAccess",
    "WeComUserBinding",
    "Workspace",
    "WorkspaceMember",
    "ResearchApproval",
    "ResearchEvent",
    "ResearchPlan",
    "ResearchStep",
    "ResearchStepDependency",
    "ResearchUsage",
    "ResearchClaim",
    "ResearchClaimEvidence",
    "ResearchReviewFinding",
]
