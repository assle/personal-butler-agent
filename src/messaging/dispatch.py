"""
消息场景分发
根据统一入站消息的 chat_type 将消息交给私聊或群聊场景 agent。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.messaging.group_policy import apply_group_policy
from src.messaging.inbound import InboundMessage


@dataclass(frozen=True)
class DispatchResult:
    """消息分发结果"""

    should_reply: bool
    reply: str = ""
    data: dict | None = None
    reason: str = ""


async def dispatch_message(
    message: InboundMessage,
    db: AsyncSession,
    private_agent,
    group_agent,
) -> DispatchResult:
    """按场景分发入站消息

    参数:
        message: 统一入站消息
        db: SQLAlchemy 异步数据库会话
        private_agent: 私聊场景 agent
        group_agent: 群聊 @ 场景 agent

    返回:
        DispatchResult: 是否需要通过 response_url 回复及回复内容
    """
    if message.msg_type not in ("text", "voice"):
        return DispatchResult(True, "暂不支持该消息类型", reason="unsupported_msg_type")

    if message.chat_type == "group":
        decision = await apply_group_policy(message, db)
        if not decision.should_reply:
            return DispatchResult(False, reason=decision.reason)
        result = await group_agent.handle(
            "group_mention",
            message.content,
            message.user_id,
            db,
            extra_state={
                "chat_type": "group",
                "chat_id": message.chat_id,
                "group_category": decision.category,
            },
        )
        return DispatchResult(True, result.reply, result.data, decision.reason)

    result = await private_agent.handle(
        "private_butler",
        message.content,
        message.user_id,
        db,
        extra_state={
            "chat_type": "single",
            "chat_id": message.chat_id,
            "source_msgid": message.msg_id,
        },
    )
    return DispatchResult(True, result.reply, result.data, "private_chat")
