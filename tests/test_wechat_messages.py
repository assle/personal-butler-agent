"""
测试企业微信 XML 消息的解析和构建

Workflow:
1. parse_encrypted_xml: 解析回调 POST 的外层加密 XML → EncryptedMessage
2. parse_inner_xml: 解析解密后的内层明文 XML → InnerMessage
3. build_reply_xml: 构建明文回复 XML
4. build_encrypted_reply_xml: 构建外层加密回复 XML
"""
from src.wechat.messages import (
    EncryptedMessage,
    InnerMessage,
    build_encrypted_reply_xml,
    build_reply_xml,
    parse_encrypted_xml,
    parse_inner_xml,
)

# ── 测试数据 ──

ENCRYPTED_XML = b"""<xml>
<ToUserName><![CDATA[wx123456]]></ToUserName>
<AgentID><![CDATA[1000001]]></AgentID>
<Encrypt><![CDATA[encrypted_content_here]]></Encrypt>
</xml>"""

INNER_XML = """<xml>
<ToUserName><![CDATA[wx123456]]></ToUserName>
<FromUserName><![CDATA[user_openid_001]]></FromUserName>
<CreateTime>1234567890</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[今天练什么]]></Content>
<MsgId>100001</MsgId>
</xml>"""


def test_parse_encrypted_xml():
    """测试解析外层加密 XML：提取 ToUserName、AgentID、Encrypt

    输入: 企业微信回调的加密 XML 字节数据
    输出: EncryptedMessage(to_user_name="wx123456", agent_id="1000001", encrypt="encrypted_content_here")
    """
    result = parse_encrypted_xml(ENCRYPTED_XML)

    assert isinstance(result, EncryptedMessage)
    assert result.to_user_name == "wx123456"
    assert result.agent_id == "1000001"
    assert result.encrypt == "encrypted_content_here"


def test_parse_inner_xml():
    """测试解析内层明文 XML：提取 FromUserName、Content、MsgType 等

    输入: 解密后的内层明文 XML 字符串
    输出: InnerMessage(from_user_name="user_openid_001", msg_type="text", content="今天练什么", ...)
    """
    result = parse_inner_xml(INNER_XML)

    assert isinstance(result, InnerMessage)
    assert result.to_user_name == "wx123456"
    assert result.from_user_name == "user_openid_001"
    assert result.create_time == 1234567890
    assert result.msg_type == "text"
    assert result.content == "今天练什么"
    assert result.msg_id == "100001"


def test_build_reply_xml():
    """测试构建明文回复 XML：生成正确的 CDATA 格式

    输入: to_user="wx123456", from_user="user_openid_001", content="今天的训练计划是：胸肌训练"
    输出: 包含正确 CDATA 内容和交换后的 to/from 用户名
    """
    xml = build_reply_xml(
        to_user="user_openid_001",
        from_user="wx123456",
        content="今天的训练计划是：胸肌训练",
    )

    assert "<ToUserName><![CDATA[user_openid_001]]></ToUserName>" in xml
    assert "<FromUserName><![CDATA[wx123456]]></FromUserName>" in xml
    assert "<MsgType><![CDATA[text]]></MsgType>" in xml
    assert "<Content><![CDATA[今天的训练计划是：胸肌训练]]></Content>" in xml


def test_build_encrypted_reply_xml():
    """测试构建外层加密回复 XML：包含 Encrypt 和 MsgSignature 等

    输入: encrypt="encrypted_reply_content", msg_signature="sig123", timestamp="1234567890", nonce="nonce123"
    输出: 包含 Encrypt、MsgSignature、TimeStamp、Nonce 的 XML 字符串
    """
    xml = build_encrypted_reply_xml(
        encrypt="encrypted_reply_content",
        msg_signature="sig123",
        timestamp="1234567890",
        nonce="nonce123",
    )

    assert "<Encrypt><![CDATA[encrypted_reply_content]]></Encrypt>" in xml
    assert "<MsgSignature><![CDATA[sig123]]></MsgSignature>" in xml
