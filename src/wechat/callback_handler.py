"""
智能机器人 URL 回调消息处理器
将回调消息规范化并交给场景分发层处理，最终通过 response_url 发送被动回复

Workflow:
1. handle_callback_message() 接收已解析的智能机器人消息体
2. InboundMessage 统一提取文本、语音识别、用户和群聊上下文
3. dispatch_message() 按私聊或群聊策略调用对应场景 agent
4. ResponseUrlReplyClient 将消息 POST 到企业微信提供的 response_url
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.messaging import InboundMessage, dispatch_message

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)
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
    private_agent,
    group_agent,
    db: AsyncSession,
):
    """处理智能机器人 URL 回调消息

    参数:
        msg: 智能机器人消息体，包含 from/text/chatid/response_url 等字段
        reply_client: response_url 回复客户端
        private_agent: 私聊场景 agent
        group_agent: 群聊 @ 场景 agent
        db: 数据库异步会话

    返回:
        None
    """
    inbound = InboundMessage.from_wecom_callback(msg)
    if inbound.msg_type == "voice" and not inbound.content:
        logger.info("AIBot callback: voice recognition empty, ignoring")
        return

    logger.info(
        "AIBot callback handler: msg_type=%s from_user=%s chat_type=%s chat_id=%s content=%s",
        inbound.msg_type,
        inbound.user_id,
        inbound.chat_type,
        inbound.chat_id,
        inbound.content[:200],
    )

    result = await dispatch_message(
        inbound,
        db,
        private_agent=private_agent,
        group_agent=group_agent,
    )
    if not result.should_reply:
        logger.info("AIBot callback: no reply, reason=%s", result.reason)
        return

    logger.info("AIBot callback handler: reply_text=%s", result.reply[:200])
    await reply_client.send_reply(inbound.response_url or "", result.reply)
