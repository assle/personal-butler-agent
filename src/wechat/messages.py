"""
企业微信 XML 消息解析和构建
负责将回调 POST 的加密 XML 解析为结构化数据，以及构建回复 XML

Workflow:
1. 收到 POST 请求 → parse_encrypted_xml(body) → EncryptedMessage
2. 解密 EncryptedMessage.encrypt → 明文 XML 字符串
3. parse_inner_xml(decrypted) → InnerMessage
4. 业务处理后 → build_reply_xml(to, from, content) → 明文回复 XML
5. 加密后 → build_encrypted_reply_xml(encrypt, ...) → 最终回复 XML
"""
import time
from dataclasses import dataclass
from xml.etree import ElementTree


@dataclass
class EncryptedMessage:
    """企业微信回调的加密外层消息"""
    to_user_name: str   # 企业 CorpID
    agent_id: str       # 应用 AgentID
    encrypt: str        # Base64 加密内容


@dataclass
class InnerMessage:
    """解密后的内层明文消息"""
    to_user_name: str    # 企业 CorpID
    from_user_name: str  # 发送者 OpenID，用作 user_id
    create_time: int     # 消息创建时间戳
    msg_type: str        # 消息类型（text/image/voice 等）
    content: str         # 消息内容（文本消息时）
    msg_id: str          # 消息 ID


def parse_encrypted_xml(body: bytes) -> EncryptedMessage:
    """解析企业微信回调的加密 XML 请求体

    参数:
        body: POST 请求的原始 XML 字节数据

    返回:
        EncryptedMessage: 包含 ToUserName、AgentID、Encrypt 的结构体
    """
    root = ElementTree.fromstring(body)
    to_user = _get_cdata(root, "ToUserName")
    agent_id = _get_cdata(root, "AgentID")
    encrypt = _get_cdata(root, "Encrypt")
    return EncryptedMessage(
        to_user_name=to_user, agent_id=agent_id, encrypt=encrypt
    )


def parse_inner_xml(decrypted: str) -> InnerMessage:
    """解析解密后的内层明文 XML

    参数:
        decrypted: 解密后的明文 XML 字符串

    返回:
        InnerMessage: 包含发送者、消息类型、内容等的结构体
    """
    root = ElementTree.fromstring(decrypted)
    return InnerMessage(
        to_user_name=_get_cdata(root, "ToUserName"),
        from_user_name=_get_cdata(root, "FromUserName"),
        create_time=int(_get_cdata(root, "CreateTime")),
        msg_type=_get_cdata(root, "MsgType"),
        content=_get_cdata(root, "Content"),
        msg_id=_get_cdata(root, "MsgId"),
    )


def build_reply_xml(to_user: str, from_user: str, content: str) -> str:
    """构建明文回复 XML（内层）

    回复时 to_user 和 from_user 需要交换：回复给发送者，来自接收者

    参数:
        to_user: 接收者 OpenID（原始消息的 from_user_name）
        from_user: 发送者 CorpID（原始消息的 to_user_name）
        content: 回复文本内容

    返回:
        str: 符合企业微信格式的明文回复 XML 字符串
    """
    return (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>{int(time.time())}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        "</xml>"
    )


def build_encrypted_reply_xml(
    encrypt: str, msg_signature: str, timestamp: str, nonce: str
) -> str:
    """构建加密回复 XML（外层），用于最终返回给企业微信

    参数:
        encrypt: 加密后的 Base64 密文
        msg_signature: 消息签名
        timestamp: 时间戳
        nonce: 随机数

    返回:
        str: 完整的加密回复 XML
    """
    return (
        "<xml>"
        f"<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
        f"<MsgSignature><![CDATA[{msg_signature}]]></MsgSignature>"
        f"<TimeStamp>{timestamp}</TimeStamp>"
        f"<Nonce><![CDATA[{nonce}]]></Nonce>"
        "</xml>"
    )


def _get_cdata(element: ElementTree.Element, tag: str) -> str:
    """从 XML 元素中获取 CDATA 文本内容

    参数:
        element: 父 XML 元素
        tag: 子元素标签名

    返回:
        str: 子元素的文本内容，若不存在则返回空字符串
    """
    child = element.find(tag)
    if child is not None and child.text is not None:
        return child.text
    return ""
