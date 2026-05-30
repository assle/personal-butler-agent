"""
Schema 模块测试
验证 Pydantic 请求/响应模型的校验和序列化逻辑

测试范围:
  - DebugMessageRequest 字段校验（必填、可选、空值拒绝）
  - DebugMessageResponse 结构正确和数据可选
"""
from datetime import datetime


def test_debug_message_request_valid():
    """验证 DebugMessageRequest 正确解析必填字段"""
    from src.schemas.request import DebugMessageRequest

    req = DebugMessageRequest(user_id="assle", message="hello")
    assert req.user_id == "assle"
    assert req.message == "hello"
    assert req.timestamp is None


def test_debug_message_request_with_timestamp():
    """验证 DebugMessageRequest 正确解析 ISO 时间戳

    测试 timestamp 字段支持 ISO 格式字符串自动转换为 datetime 对象。
    """
    from src.schemas.request import DebugMessageRequest

    ts = "2026-05-29T16:30:00"
    req = DebugMessageRequest(user_id="assle", message="hello", timestamp=ts)
    assert req.timestamp == datetime.fromisoformat(ts)


def test_debug_message_request_empty_message_fails():
    """验证空消息被 Pydantic 校验拒绝"""
    from src.schemas.request import DebugMessageRequest
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DebugMessageRequest(user_id="assle", message="")


def test_debug_message_response_structure():
    """验证 DebugMessageResponse 结构正确，包含所有字段"""
    from src.schemas.response import DebugMessageResponse

    resp = DebugMessageResponse(
        intent="qa",
        confidence=0.95,
        response="Hello!",
        data={"key": "value"},
    )
    assert resp.intent == "qa"
    assert resp.confidence == 0.95
    assert resp.response == "Hello!"
    assert resp.data == {"key": "value"}


def test_debug_message_response_data_optional():
    """验证 DebugMessageResponse 的 data 字段为可选"""
    from src.schemas.response import DebugMessageResponse

    resp = DebugMessageResponse(
        intent="unknown",
        confidence=0.0,
        response="Sorry, I don't understand.",
    )
    assert resp.data is None
