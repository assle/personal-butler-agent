"""
智能机器人 URL 回调消息处理器
将可回复消息交给 ButlerAgent 处理，最终通过 response_url 发送被动回复

Workflow:
1. handle_callback_message() 接收已解析的智能机器人消息体
2. 文本/语音消息走 ButlerAgent；群聊非触发消息仅入库不回复
3. 处理结果构造成 markdown 消息体
4. ResponseUrlReplyClient 将消息 POST 到企业微信提供的 response_url
"""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.butler import ButlerAgent
from src.agents.registry import AgentRegistry
from src.intent.router import IntentRouter

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)

_SUMMARIZE_KEYWORDS = ["总结", "摘要", "概括", "汇总"]


class ResponseUrlReplyClient:
    """通过智能机器人 response_url 发送被动回复的客户端"""

    def __init__(self, post_json: Callable[[str, dict], Awaitable[bool]] | None = None):
        """初始化回复客户端

        参数:
            post_json: 可选注入的异步发送函数，测试时用于替换真实 HTTP 请求
        """
        self._post_json = post_json

    async def send_reply(self, response_url: str, content: str) -> bool:
        """向 response_url 发送 markdown 回复

        参数:
            response_url: 企业微信回调消息体中的临时回复 URL
            content: 回复文本

        返回:
            bool: 发送成功返回 True
        """
        if not response_url:
            logger.warning("AIBot callback: missing response_url, cannot reply")
            return False
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        if self._post_json is not None:
            return await self._post_json(response_url, payload)
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(response_url, json=payload)
            if response.status_code >= 400:
                logger.warning(
                    "AIBot callback: response_url post failed status=%s body=%s",
                    response.status_code,
                    response.text[:200],
                )
                return False
            return True


async def handle_callback_message(
    msg: dict,
    reply_client: ResponseUrlReplyClient,
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    butler_agent: ButlerAgent,
    db: AsyncSession,
):
    """处理智能机器人 URL 回调消息

    参数:
        msg: 智能机器人消息体，包含 from/text/chatid/response_url 等字段
        reply_client: response_url 回复客户端
        intent_router: 兼容保留的意图路由器，可回复消息不再直接使用
        agent_registry: 兼容保留的 agent 注册表，可回复消息不再直接使用
        butler_agent: 小管家总控 agent，用于处理可回复文本和语音消息
        db: 数据库异步会话
    """
    from_user = msg.get("from", {}).get("userid", "")
    msg_type = msg.get("msgtype", "text")
    content = _extract_content(msg, msg_type)
    if msg_type == "voice" and not content:
        logger.info("AIBot callback: voice recognition empty, ignoring")
        return

    chat_id = msg.get("chatid", "")
    chat_type = msg.get("chattype", "single")
    response_url = msg.get("response_url", "")
    logger.info(
        "AIBot callback handler: msg_type=%s from_user=%s chat_type=%s chat_id=%s content=%s",
        msg_type, from_user, chat_type, chat_id, content[:200],
    )

    extra_state: dict = {"chat_type": chat_type, "chat_id": chat_id or None}

    is_group_trigger = False
    if chat_type == "group" and chat_id:
        from src.models.group_message import GroupMessage
        await GroupMessage.save(db, chat_id, from_user, content, int(time.time()))
        await GroupMessage.cleanup(db, chat_id, keep=200)
        if _is_summarize_trigger(content):
            is_group_trigger = True
        else:
            logger.info("AIBot callback: non-trigger group message, no reply")
            return

    reply_text = await _build_reply_text(
        msg_type=msg_type,
        content=content,
        from_user=from_user,
        db=db,
        intent_router=intent_router,
        agent_registry=agent_registry,
        butler_agent=butler_agent,
        extra_state=extra_state,
        is_group_trigger=is_group_trigger,
    )
    logger.info("AIBot callback handler: reply_text=%s", reply_text[:200])
    await reply_client.send_reply(response_url, reply_text)


def _extract_content(msg: dict, msg_type: str) -> str:
    """提取智能机器人消息文本内容

    参数:
        msg: 智能机器人消息体
        msg_type: 消息类型

    返回:
        str: 可送入意图路由的文本内容
    """
    if msg_type == "voice":
        return msg.get("voice", {}).get("content", "")
    return msg.get("text", {}).get("content", "")


async def _build_reply_text(
    msg_type: str,
    content: str,
    from_user: str,
    db: AsyncSession,
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    butler_agent: ButlerAgent,
    extra_state: dict,
    is_group_trigger: bool,
) -> str:
    """根据消息内容生成回复文本

    参数:
        msg_type: 消息类型
        content: 消息文本
        from_user: 发送者 userid
        db: 数据库异步会话
        intent_router: 兼容保留的意图路由器，可回复消息不再直接使用
        agent_registry: 兼容保留的 agent 注册表，可回复消息不再直接使用
        butler_agent: 小管家总控 agent
        extra_state: agent 额外上下文
        is_group_trigger: 是否为群聊总结触发消息

    返回:
        str: 回复文本
    """
    if msg_type not in ("text", "voice"):
        return "暂不支持该消息类型"
    try:
        if is_group_trigger:
            logger.info("AIBot callback handler: group trigger routed to butler")
        result = await butler_agent.handle("butler", content, from_user, db, extra_state=extra_state)
        return result.reply
    except Exception as e:
        logger.exception("AIBot callback: butler agent error: %s", e)
        return "LLM 服务暂时不可用，请稍后重试。"


def _is_summarize_trigger(content: str) -> bool:
    """检测消息是否触发群聊总结

    参数:
        content: 群聊消息文本

    返回:
        bool: 命中总结关键词返回 True
    """
    return any(kw in content for kw in _SUMMARIZE_KEYWORDS)
