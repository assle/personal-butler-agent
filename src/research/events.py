"""研究审计事件写入"""
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research_execution import ResearchEvent

logger = logging.getLogger(__name__)

# 需要脱敏的字段名关键词
_SECRET_KEYWORDS = {"api_key", "secret", "token", "password", "credential"}
_REDACTED_VALUE = "[REDACTED]"


class EventWriter:
    """追加审计事件，自动脱敏敏感字段"""

    async def append(
        self,
        db: AsyncSession,
        *,
        workspace_id: str,
        task_id: str,
        step_id: str | None = None,
        event_type: str,
        payload: dict | None = None,
        trace_id: str = "",
    ) -> ResearchEvent:
        """追加一条审计事件

        参数:
            db: 异步数据库会话
            workspace_id: 工作空间 ID
            task_id: 研究任务 ID
            step_id: 可选步骤 ID
            event_type: 事件类型（如 tool.called、plan.created）
            payload: 事件载荷
            trace_id: 追踪 ID

        返回:
            ResearchEvent: 已持久化事件
        """
        safe_payload = _redact_secrets(payload or {})
        event = ResearchEvent(
            workspace_id=workspace_id,
            task_id=task_id,
            step_id=step_id,
            trace_id=trace_id,
            event_type=event_type,
            payload=safe_payload,
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        await db.flush()
        return event


def _redact_secrets(data: dict) -> dict:
    """递归脱敏字典中的敏感字段

    参数:
        data: 原始载荷

    返回:
        dict: 脱敏后的载荷
    """
    if not isinstance(data, dict):
        return data
    result = {}
    for key, value in data.items():
        if any(kw in key.lower() for kw in _SECRET_KEYWORDS):
            result[key] = _REDACTED_VALUE
        elif isinstance(value, dict):
            result[key] = _redact_secrets(value)
        elif isinstance(value, list):
            result[key] = [
                _redact_secrets(v) if isinstance(v, dict) else v
                for v in value
            ]
        else:
            result[key] = value
    return result
