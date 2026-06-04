"""
Webhook 内容生成 Agent 状态定义
定义定时群推送正文生成所需字段。
"""
from typing import TypedDict


class WebhookComposerState(TypedDict, total=False):
    """WebhookComposerAgent 状态"""

    intent: str
    message: str
    user_id: str
    chat_type: str
    chat_id: str | None
    reply: str
    error: str | None
    llm: object
