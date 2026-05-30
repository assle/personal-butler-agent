"""
企业微信群机器人 Webhook 推送客户端
通过 POST JSON 到 Webhook URL 向群聊发送文本 / Markdown 消息

Workflow:
1. 创建 WechatWebhookClient(webhook_url)
2. 调用 send_text(content) 或 send_markdown(content)
3. 内部 POST JSON 到 webhook URL，检查 errcode 判断成功/失败
"""
import httpx


class WechatWebhookClient:
    """企业微信群机器人 Webhook 推送客户端"""

    def __init__(self, webhook_url: str, client: httpx.AsyncClient | None = None):
        """初始化推送客户端

        参数:
            webhook_url: 群机器人的 Webhook URL
            client: 可选，注入 httpx.AsyncClient（用于测试或连接复用）
        """
        self._url = webhook_url
        self._client = client

    async def _post(self, payload: dict) -> bool:
        """向 Webhook URL 发送 JSON 并检查响应

        参数:
            payload: 消息 JSON 体

        返回:
            bool: errcode == 0 返回 True，否则返回 False
        """
        if self._client is not None:
            try:
                resp = await self._client.post(self._url, json=payload)
                data = resp.json()
                return data.get("errcode") == 0
            except Exception:
                return False

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self._url, json=payload)
                data = resp.json()
                return data.get("errcode") == 0
            except Exception:
                return False

    async def send_text(self, content: str) -> bool:
        """发送文本消息到群聊

        参数:
            content: 消息文本内容

        返回:
            bool: 发送成功返回 True
        """
        return await self._post({
            "msgtype": "text",
            "text": {"content": content},
        })

    async def send_markdown(self, content: str) -> bool:
        """发送 Markdown 格式消息到群聊

        参数:
            content: Markdown 格式的文本内容

        返回:
            bool: 发送成功返回 True
        """
        return await self._post({
            "msgtype": "markdown",
            "markdown": {"content": content},
        })
