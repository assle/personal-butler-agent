"""
企业微信集成模块
提供消息加解密、签名验证、WebSocket 长连接客户端和回调路由功能

Workflow:
1. crypto.py: AES-256-CBC 加解密 + SHA1 签名验证（纯函数，无外部依赖）
2. messages.py: XML 消息解析（EncryptedMessage → InnerMessage）和构建
3. ws_client.py: WebSocket 长连接客户端（智能机器人消息收发和主动推送）
4. message_handler.py: 长连接消息处理回调（意图路由 → agent → 回复）
5. router.py: 自建应用 FastAPI 路由工厂（GET 回调验证 + POST 消息接收 → 意图路由 → agent → 加密回复）
"""
from .crypto import (
    CorpIDMismatch,
    DecryptError,
    SignatureError,
    decrypt,
    encrypt,
    verify_signature,
)
from .messages import (
    EncryptedMessage,
    InnerMessage,
    build_encrypted_reply_xml,
    build_reply_xml,
    parse_encrypted_xml,
    parse_inner_xml,
)
from .router import create_wechat_router
from .ws_client import WeComWSClient
from .message_handler import handle_ws_message

__all__ = [
    # crypto
    "verify_signature",
    "encrypt",
    "decrypt",
    "SignatureError",
    "DecryptError",
    "CorpIDMismatch",
    # messages
    "EncryptedMessage",
    "InnerMessage",
    "parse_encrypted_xml",
    "parse_inner_xml",
    "build_reply_xml",
    "build_encrypted_reply_xml",
    # ws_client
    "WeComWSClient",
    # message_handler
    "handle_ws_message",
    # router
    "create_wechat_router",
]
