from datetime import datetime


def test_debug_message_request_valid():
    from src.schemas.request import DebugMessageRequest

    req = DebugMessageRequest(user_id="assle", message="hello")
    assert req.user_id == "assle"
    assert req.message == "hello"
    assert req.timestamp is None


def test_debug_message_request_with_timestamp():
    from src.schemas.request import DebugMessageRequest

    ts = "2026-05-29T16:30:00"
    req = DebugMessageRequest(user_id="assle", message="hello", timestamp=ts)
    assert req.timestamp == datetime.fromisoformat(ts)


def test_debug_message_request_empty_message_fails():
    from src.schemas.request import DebugMessageRequest
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DebugMessageRequest(user_id="assle", message="")


def test_debug_message_response_structure():
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
    from src.schemas.response import DebugMessageResponse

    resp = DebugMessageResponse(
        intent="unknown",
        confidence=0.0,
        response="Sorry, I don't understand.",
    )
    assert resp.data is None
