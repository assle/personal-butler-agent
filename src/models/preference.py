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


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(nullable=False, unique=True)
    preferences: Mapped[str] = mapped_column(
        default=lambda: json.dumps(DEFAULT_PREFERENCES, ensure_ascii=False),
        nullable=False,
    )
    created_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now().isoformat(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now().isoformat(), nullable=False
    )
