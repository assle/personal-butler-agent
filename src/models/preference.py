"""
用户偏好 ORM 模型
存储用户在健身和饮食方面的偏好设置，以 JSON 格式持久化

在总流程中的位置:
  各 agent 的节点函数 → select(UserPreference) → 读取偏好 → 注入 LLM prompt
  新用户无记录时使用 DEFAULT_PREFERENCES 默认值
"""
from datetime import datetime
import json
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base import Base

DEFAULT_PREFERENCES = {
    "fitness": {
        "body": {"height_cm": None, "weight_kg": None, "age": None},
        "goal": "general_fitness",
        "level": "beginner",
    },
    "meal": {
        "calorie_target": None,
        "diet_type": "balanced",
        "allergies": [],
    },
}
"""新用户的默认偏好配置，包含 fitness（身体数据+目标+水平）和 meal（热量+饮食类型+过敏原）"""


class UserPreference(Base):
    """用户偏好模型，每个 user_id 对应一行记录"""

    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    """自增主键"""

    user_id: Mapped[str] = mapped_column(nullable=False, unique=True)
    """用户唯一标识（企业微信 OpenID 或调试 ID）"""

    preferences: Mapped[str] = mapped_column(
        default=lambda: json.dumps(DEFAULT_PREFERENCES, ensure_ascii=False),
        nullable=False,
    )
    """JSON 字符串，存储用户的健身和饮食偏好"""

    created_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now().isoformat(), nullable=False
    )
    """创建时间 ISO 格式"""

    updated_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now().isoformat(), nullable=False
    )
    """最后更新时间 ISO 格式"""
