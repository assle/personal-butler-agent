"""
企业微信群 webhook 推送客户端
负责构造 markdown 消息并执行带超时和错误处理的 HTTP 请求。
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class WebhookPushClient:
    """企业微信群机器人 webhook 推送客户端"""

    def __init__(self, timeout_seconds: int = 10):
        """初始化 webhook 推送客户端

        参数:
            timeout_seconds: HTTP 请求超时时间，单位秒

        返回:
            None
        """
        self._timeout_seconds = timeout_seconds

    async def send_markdown(
        self,
        webhook_url: str,
        content: str,
        mentioned_list: list[str] | None = None,
    ) -> bool:
        """发送 markdown 消息到企业微信群 webhook

        参数:
            webhook_url: 企业微信群机器人 webhook 地址
            content: 要发送的 markdown 内容
            mentioned_list: 可选 @ 用户列表；markdown 内容中仍会保留 <@userid> 语法

        返回:
            bool: 发送成功返回 True，否则返回 False
        """
        if mentioned_list:
            missing_mentions = [
                f"<@{user_id}>"
                for user_id in mentioned_list
                if user_id and f"<@{user_id}>" not in content
            ]
            if missing_mentions:
                content = f"{' '.join(missing_mentions)} {content}"
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(webhook_url, json=payload)
        except httpx.HTTPError:
            logger.info("Scheduler webhook: request failed", exc_info=True)
            return False

        if response.status_code >= 400:
            logger.warning(
                "Scheduler webhook: post failed status=%s body=%s",
                response.status_code,
                response.text[:200],
            )
            return False
        return True
