"""
企业微信用户信息缓存 ORM 模型
存储通过企微服务端 API 查询到的用户详细信息，TTL 24h

在总流程中的位置:
  WeComUserService.get_user() → 查 WeComUser 表 → 缓存命中则直接返回 → 未命中则调 API 并 upsert
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base import Base

# 用户信息缓存有效期：24 小时
_USER_TTL_HOURS = 24


class WeComUser(Base):
    """企业微信用户信息缓存模型"""

    __tablename__ = "wecom_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    """自增主键"""

    userid: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    """企业微信用户 ID（如 zhangsan），唯一索引"""

    name: Mapped[Optional[str]] = mapped_column(nullable=True)
    """用户姓名"""

    department: Mapped[Optional[str]] = mapped_column(nullable=True)
    """所属部门（JSON 数组字符串，如 '[1, 2]'）"""

    avatar: Mapped[Optional[str]] = mapped_column(nullable=True)
    """头像 URL"""

    position: Mapped[Optional[str]] = mapped_column(nullable=True)
    """职位"""

    mobile: Mapped[Optional[str]] = mapped_column(nullable=True)
    """手机号"""

    email: Mapped[Optional[str]] = mapped_column(nullable=True)
    """邮箱"""

    last_synced_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now(timezone.utc).isoformat(), nullable=False
    )
    """最后同步时间（ISO 格式 UTC），用于判断缓存是否过期"""

    @classmethod
    def is_fresh(cls, synced_at: str) -> bool:
        """判断缓存的同步时间是否仍在有效期内

        参数:
            synced_at: ISO 格式的最后同步时间字符串

        返回:
            bool: 未超过 24h 返回 True
        """
        try:
            t = datetime.fromisoformat(synced_at)
        except ValueError:
            return False
        now = datetime.now(timezone.utc)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (now - t) < timedelta(hours=_USER_TTL_HOURS)
