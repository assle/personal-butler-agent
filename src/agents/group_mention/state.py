"""
群聊 @ Agent 状态定义
定义群聊受限场景中从分类到回复生成的状态字段。
"""
from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class GroupMentionState(TypedDict, total=False):
    """群聊 @ Agent 图状态"""

    intent: str
    message: str
    user_id: str
    chat_type: str
    chat_id: str | None
    category: str | None
    messages: Annotated[list[AnyMessage], add_messages]
    reply: str
    data: dict | None
    error: str | None
    llm: object
    summary_agent: object
    weather_service: object
    poll_agent: object  # 新增
    db: object
