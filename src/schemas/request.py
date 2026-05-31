"""
请求 Schema 定义
Pydantic 模型定义 API 请求体的字段和校验规则

在总流程中的位置:
  POST /api/debug/message → FastAPI 自动将 JSON body 解析为 DebugMessageRequest
  → intent_router.route(req.message) → agent.handle(req.message, req.user_id, db)
"""
from datetime import datetime
from pydantic import BaseModel, Field


class DebugMessageRequest(BaseModel):
    """调试消息请求体 Schema"""

    user_id: str = Field(min_length=1)
    """用户唯一标识，不能为空"""

    message: str = Field(min_length=1)
    """用户消息文本，不能为空"""

    timestamp: datetime | None = None
    """消息时间戳（可选），ISO 格式"""

    chat_type: str = "single"
    """会话类型："single"（私聊）或 "group"（群聊），默认 single"""

    chat_id: str = ""
    """群聊 ID，chat_type="group" 时使用"""
