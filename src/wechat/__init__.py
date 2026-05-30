"""
企业微信集成模块
提供消息加解密、签名验证、Webhook 推送和回调路由功能

Workflow:
1. crypto.py: AES-256-CBC 加解密 + SHA1 签名验证（纯函数，无外部依赖）
2. messages.py: XML 消息解析（EncryptedMessage → InnerMessage）和构建
3. webhook.py: 群机器人 Webhook 推送客户端（发送 text/markdown 到群聊）
4. router.py: FastAPI 路由工厂（GET 回调验证 + POST 消息接收 → 意图路由 → agent → 加密回复）
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
from .webhook import WechatWebhookClient

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
    # webhook
    "WechatWebhookClient",
    # router
    "create_wechat_router",
]
