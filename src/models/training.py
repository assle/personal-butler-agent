"""
训练记录 ORM 模型
存储每次训练的具体记录：部位、动作、组数、次数、重量等

在总流程中的位置:
  FitnessAgent persist_records 节点 → TrainingRecord 实例 → db.add → flush 写入
  fetch_training_history 节点 → select(TrainingRecord) → 查询近一周记录
"""
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base import Base


class TrainingRecord(Base):
    """训练记录模型，每次打卡创建一个或多个记录"""

    __tablename__ = "training_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    """自增主键"""

    user_id: Mapped[str] = mapped_column(nullable=False)
    """用户唯一标识"""

    date: Mapped[str] = mapped_column(nullable=False)
    """训练日期，YYYY-MM-DD 格式"""

    muscle_group: Mapped[str] = mapped_column(nullable=False)
    """训练部位：胸/背/腿/肩/臂/核心"""

    exercise: Mapped[str] = mapped_column(nullable=False)
    """动作名称，如卧推、深蹲"""

    sets: Mapped[int] = mapped_column(nullable=False)
    """组数"""

    reps: Mapped[int] = mapped_column(nullable=False)
    """每组次数"""

    weight_kg: Mapped[Optional[float]] = mapped_column(nullable=True)
    """使用重量（kg），自重训练可为 null"""

    created_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now().isoformat(), nullable=False
    )
    """记录创建时间 ISO 格式"""
