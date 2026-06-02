"""
训练记录 ORM 模型
存储每次训练的具体记录：支持力量训练和有氧训练两种类型

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

    training_type: Mapped[str] = mapped_column(default="strength", nullable=False)
    """训练类型：strength（力量训练）或 cardio（有氧训练）"""

    exercise: Mapped[str] = mapped_column(nullable=False)
    """动作名称，如卧推、深蹲、爬坡、跑步"""

    # --- 力量训练字段 ---
    muscle_group: Mapped[Optional[str]] = mapped_column(nullable=True)
    """训练部位：胸/背/腿/肩/臂/核心（有氧训练可为空）"""

    sets: Mapped[Optional[int]] = mapped_column(nullable=True)
    """组数（有氧训练可为空）"""

    reps: Mapped[Optional[int]] = mapped_column(nullable=True)
    """每组次数（有氧训练可为空）"""

    weight_kg: Mapped[Optional[float]] = mapped_column(nullable=True)
    """使用重量（kg），自重训练可为 null"""

    # --- 有氧训练字段 ---
    duration_minutes: Mapped[Optional[float]] = mapped_column(nullable=True)
    """训练时长（分钟）"""

    speed: Mapped[Optional[float]] = mapped_column(nullable=True)
    """速度（km/h）"""

    incline: Mapped[Optional[float]] = mapped_column(nullable=True)
    """坡度"""

    calories: Mapped[Optional[float]] = mapped_column(nullable=True)
    """消耗卡路里"""

    created_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now().isoformat(), nullable=False
    )
    """记录创建时间 ISO 格式"""
