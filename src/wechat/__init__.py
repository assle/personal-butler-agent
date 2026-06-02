"""
企业微信集成模块
提供智能机器人 URL 回调入站、response_url 回复，以及保留的 WebSocket 客户端兼容代码

Workflow:
1. callback_router.py: URL 回调 GET 验证和 POST 消息接收
2. callback_inbox.py: 入站消息按 msgid 幂等落库
3. callback_handler.py: 意图路由 → agent → response_url 回复
4. ws_client.py/message_handler.py: 旧长连接兼容模块，不在 main.py 中启动
"""
from .ws_client import WeComWSClient
from .message_handler import handle_ws_message
from .callback_handler import ResponseUrlReplyClient, handle_callback_message

__all__ = [
    "WeComWSClient",
    "handle_ws_message",
    "ResponseUrlReplyClient",
    "handle_callback_message",
]
