"""
群消息策略
统一负责群消息保存、历史清理和是否触发群聊机器人回复的判断。

Workflow:
1. dispatch_message() 收到 group 入站消息
2. apply_group_policy() 保存可用群消息到 group_messages
3. 根据关键词和消息内容决定是否进入 GroupMentionAgent
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.messaging.inbound import InboundMessage
from src.models.group_message import GroupMessage
from src.models.poll import Poll

SUMMARY_KEYWORDS = ("总结", "摘要", "概括", "汇总")
WEATHER_KEYWORDS = ("天气", "气温", "下雨", "降雨")
QUESTION_MARKERS = ("?", "？", "吗", "怎么", "如何", "为什么", "什么")
POLL_CREATE_KEYWORDS = ("创建投票", "发起投票", "新建投票")
POLL_VIEW_KEYWORDS = ("投票结果", "查看投票", "投票情况")
POLL_END_KEYWORDS = ("结束投票", "关闭投票", "停止投票")
TRANSLATE_KEYWORDS = ("翻译成", "翻译为", "翻译")


@dataclass(frozen=True)
class GroupPolicyDecision:
    """群消息策略判断结果"""

    should_reply: bool
    reason: str
    category: str | None = None


def classify_group_trigger(content: str) -> str | None:
    """根据群消息内容判断触发类别

    参数:
        content: 群消息文本内容

    返回:
        str | None: 触发类别；未触发返回 None
    """
    normalized = content.strip().lower()
    if not normalized:
        return None
    if any(keyword in normalized for keyword in SUMMARY_KEYWORDS):
        return "summarize_group"
    if any(keyword in normalized for keyword in WEATHER_KEYWORDS):
        return "weather"
    if any(keyword in normalized for keyword in POLL_CREATE_KEYWORDS):
        return "poll_create"
    if any(keyword in normalized for keyword in POLL_END_KEYWORDS):
        return "poll_end"
    if any(keyword in normalized for keyword in POLL_VIEW_KEYWORDS):
        return "poll_view"
    if any(keyword in normalized for keyword in TRANSLATE_KEYWORDS):
        return "translate"
    if any(marker in normalized for marker in QUESTION_MARKERS):
        return "simple_qa"
    return None


async def _detect_vote_action(db: AsyncSession, chat_id: str, content: str) -> str | None:
    """检测是否为投票动作：群内有 active poll 且消息看起来像投票

    参数:
        db: 异步数据库会话
        chat_id: 群聊 ID
        content: 消息文本

    返回:
        str | None: "poll_vote" 或 None
    """
    normalized = content.strip()
    # 匹配: A, 选A, 投票A, 选 A
    if re.match(r"^(选\s*)?[A-Za-z]$", normalized) or re.match(r"^投票\s*[A-Za-z]$", normalized):
        result = await db.execute(
            select(Poll).where(
                Poll.chat_id == chat_id,
                Poll.status == "active",
            ).limit(1)
        )
        if result.scalar_one_or_none() is not None:
            return "poll_vote"
    return None


async def apply_group_policy(
    message: InboundMessage,
    db: AsyncSession,
) -> GroupPolicyDecision:
    """保存群消息并判断是否需要回复

    参数:
        message: 统一入站消息对象
        db: SQLAlchemy 异步数据库会话

    返回:
        GroupPolicyDecision: 是否回复及触发类别
    """
    if not message.content.strip():
        return GroupPolicyDecision(False, "empty_content")
    if not message.chat_id:
        return GroupPolicyDecision(False, "missing_chat_id")

    await GroupMessage.save(
        db,
        message.chat_id,
        message.user_id,
        message.content,
        int(time.time()),
    )
    await GroupMessage.cleanup(db, message.chat_id, keep=200)

    category = classify_group_trigger(message.content)
    if category is not None:
        return GroupPolicyDecision(True, "trigger", category)

    # 未命中触发词时，检查是否为投票动作
    content_stripped = message.content.strip()
    if 1 <= len(content_stripped) <= 10:
        vote_category = await _detect_vote_action(db, message.chat_id, content_stripped)
        if vote_category is not None:
            return GroupPolicyDecision(True, "trigger", vote_category)

    return GroupPolicyDecision(False, "non_trigger")
