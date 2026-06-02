"""
企业微信集成模块
提供 WebSocket 长连接客户端和消息处理功能（智能机器人）

Workflow:
1. ws_client.py: WebSocket 长连接客户端（智能机器人消息收发和主动推送）
2. message_handler.py: 长连接消息处理回调（意图路由 → agent → 回复）
"""
from .ws_client import WeComWSClient
from .message_handler import handle_ws_message

__all__ = [
    "WeComWSClient",
    "handle_ws_message",
]
