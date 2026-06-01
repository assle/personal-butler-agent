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

# 语音消息 XML（包含 Recognition 字段）
VOICE_INNER_XML = """<xml>
<ToUserName><![CDATA[wx123456]]></ToUserName>
<FromUserName><![CDATA[user_voice_001]]></FromUserName>
<CreateTime>1234567890</CreateTime>
<MsgType><![CDATA[voice]]></MsgType>
<Recognition><![CDATA[今天练胸肌]]></Recognition>
<MsgId>100003</MsgId>
</xml>"""

# 语音消息 XML（不含 Recognition 字段）
VOICE_INNER_XML_NO_RECOGNITION = """<xml>
<ToUserName><![CDATA[wx123456]]></ToUserName>
<FromUserName><![CDATA[user_voice_002]]></FromUserName>
<CreateTime>1234567890</CreateTime>
<MsgType><![CDATA[voice]]></MsgType>
<MsgId>100004</MsgId>
</xml>"""

# 群聊消息的 XML 包含 ChatId 和 ChatType
INNER_XML_GROUP = """<xml>
<ToUserName><![CDATA[wx123456]]></ToUserName>
<FromUserName><![CDATA[user_openid_002]]></FromUserName>
<CreateTime>1780217822</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[@机器人 总结一下群消息]]></Content>
<MsgId>100002</MsgId>
<ChatId><![CDATA[group_chat_123]]></ChatId>
<ChatType><![CDATA[group]]></ChatType>
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
    """测试解析内层明文 XML（私聊）：提取基本字段，chat 字段使用默认值

    输入: 解密后的内层明文 XML 字符串（无 ChatId/ChatType）
    输出: InnerMessage(..., chat_id="", chat_type="single")
    """
    result = parse_inner_xml(INNER_XML)

    assert isinstance(result, InnerMessage)
    assert result.to_user_name == "wx123456"
    assert result.from_user_name == "user_openid_001"
    assert result.create_time == 1234567890
    assert result.msg_type == "text"
    assert result.content == "今天练什么"
    assert result.msg_id == "100001"
    # 私聊消息：chat 字段为空
    assert result.chat_id == ""
    assert result.chat_type == "single"
    assert result.recognition == ""


def test_parse_inner_xml_group_chat():
    """测试解析群聊内层明文 XML：提取 ChatId 和 ChatType

    输入: 包含 ChatId="group_chat_123" 和 ChatType="group" 的 XML
    输出: InnerMessage(chat_id="group_chat_123", chat_type="group")
    """
    result = parse_inner_xml(INNER_XML_GROUP)

    assert isinstance(result, InnerMessage)
    assert result.to_user_name == "wx123456"
    assert result.from_user_name == "user_openid_002"
    assert result.msg_type == "text"
    assert result.content == "@机器人 总结一下群消息"
    assert result.msg_id == "100002"
    # 群聊消息：chat 字段有值
    assert result.chat_id == "group_chat_123"
    assert result.chat_type == "group"
    assert result.recognition == ""


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


def test_parse_inner_xml_voice_recognition():
    """测试解析语音消息 XML：正确提取 Recognition 字段

    输入: 包含 <Recognition> 的 voice 消息 XML
    输出: InnerMessage(recognition="今天练胸肌", msg_type="voice", content="")
    """
    result = parse_inner_xml(VOICE_INNER_XML)

    assert result.msg_type == "voice"
    assert result.recognition == "今天练胸肌"
    assert result.content == ""


def test_parse_inner_xml_voice_no_recognition():
    """测试解析没有 Recognition 字段的语音消息 XML：recognition 为空字符串

    输入: 无 <Recognition> 标签的 voice 消息 XML
    输出: InnerMessage(recognition="")
    """
    result = parse_inner_xml(VOICE_INNER_XML_NO_RECOGNITION)

    assert result.msg_type == "voice"
    assert result.recognition == ""


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
