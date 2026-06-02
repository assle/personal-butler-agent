"""ORM 模型包，包含 SQLite 数据表映射"""
from src.models.training import TrainingRecord
from src.models.preference import UserPreference
from src.models.group_message import GroupMessage
from src.models.conversation import ConversationMessage, ConversationSummary

__all__ = ["TrainingRecord", "UserPreference", "GroupMessage", "ConversationMessage", "ConversationSummary"]
