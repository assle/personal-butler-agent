"""
统一入站消息模型
把企业微信 URL 回调消息转换成场景分发层使用的统一结构。

Workflow:
1. callback_handler 接收已解析的企业微信消息体
2. InboundMessage.from_wecom_callback() 提取用户、群聊、文本和回复 URL
3. dispatch_message() 根据 chat_type 把消息交给对应场景 agent
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
    """统一入站消息对象"""

    source: str
    msg_id: str
    msg_type: str
    user_id: str
    content: str
    chat_type: str
    chat_id: str | None
    response_url: str | None
    raw: dict[str, Any]

    @classmethod
    def from_wecom_callback(cls, raw: dict[str, Any]) -> "InboundMessage":
        """从企业微信智能机器人回调消息体构造统一入站消息

        参数:
            raw: 已解密并提取 body 后的企业微信消息体

        返回:
            InboundMessage: 供场景分发层使用的统一消息对象
        """
        msg_type = str(raw.get("msgtype", "text") or "text")
        if msg_type == "voice":
            content = str(raw.get("voice", {}).get("content", "") or "")
        else:
            content = str(raw.get("text", {}).get("content", "") or "")

        chat_id = str(raw.get("chatid", "") or "").strip() or None
        return cls(
            source="wecom_callback",
            msg_id=str(raw.get("msgid", "") or ""),
            msg_type=msg_type,
            user_id=str(raw.get("from", {}).get("userid", "") or ""),
            content=content,
            chat_type=str(raw.get("chattype", "single") or "single"),
            chat_id=chat_id,
            response_url=str(raw.get("response_url", "") or "") or None,
            raw=raw,
        )
