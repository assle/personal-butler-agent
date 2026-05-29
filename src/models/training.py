from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base import Base


class TrainingRecord(Base):
    __tablename__ = "training_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(nullable=False)
    date: Mapped[str] = mapped_column(nullable=False)
    muscle_group: Mapped[str] = mapped_column(nullable=False)
    exercise: Mapped[str] = mapped_column(nullable=False)
    sets: Mapped[int] = mapped_column(nullable=False)
    reps: Mapped[int] = mapped_column(nullable=False)
    weight_kg: Mapped[Optional[float]] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now().isoformat(), nullable=False
    )
