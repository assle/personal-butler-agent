"""ORM 模型包，包含 SQLite 数据表映射"""
from src.models.training import TrainingRecord
from src.models.preference import UserPreference

__all__ = ["TrainingRecord", "UserPreference"]
