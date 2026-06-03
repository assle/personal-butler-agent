"""
调试 API 端点测试
验证 POST /api/debug/message 端到端流程：调试路由 → ButlerAgent → JSON 响应

测试范围:
  - 私聊消息统一交给 ButlerAgent 处理
  - 群聊非触发消息继续静默收集
  - 群聊触发消息交给 ButlerAgent 处理
"""
from unittest.mock import AsyncMock, patch

import pytest
import src.main
from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.response import AgentResponse


@pytest.mark.asyncio
async def test_debug_endpoint_private_chat_uses_butler_agent(http_client):
    """验证私聊调试消息统一交给 ButlerAgent

    模拟 ButlerAgent 返回固定回复，确认响应 intent/confidence 稳定为 butler/1.0。

    参数:
        http_client: httpx 异步客户端 fixture
    """
    with patch(
        "src.main.butler_agent.handle",
        new_callable=AsyncMock,
        return_value=AgentResponse(
            reply="你好！有什么可以帮你的？",
            data={"intent": "butler"},
        ),
    ) as mock_handle:
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "你好",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "butler"
    assert body["confidence"] == 1.0
    assert body["response"] == "你好！有什么可以帮你的？"
    args, kwargs = mock_handle.await_args
    assert args[:3] == ("butler", "你好", "assle")
    assert isinstance(args[3], AsyncSession)
    assert kwargs == {"extra_state": {"chat_type": "single", "chat_id": None}}


@pytest.mark.asyncio
async def test_debug_endpoint_group_non_trigger_collects_without_butler(http_client):
    """验证群聊非触发消息只收集不调用 ButlerAgent

    群聊普通消息应保存为 collect_group 响应，避免打扰群聊。

    参数:
        http_client: httpx 异步客户端 fixture
    """
    with patch(
        "src.main.butler_agent.handle",
        new_callable=AsyncMock,
    ) as mock_handle:
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "今天午饭不错",
                "chat_type": "group",
                "chat_id": "chat-a",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "collect_group"
    assert body["confidence"] == 1.0
    assert body["response"] == ""
    assert body["data"] == {"chat_id": "chat-a", "saved": True}
    mock_handle.assert_not_called()


@pytest.mark.asyncio
async def test_debug_endpoint_group_trigger_uses_butler_agent(http_client):
    """验证群聊触发消息交给 ButlerAgent

    命中总结类关键词时，调试路由应带群聊上下文调用 ButlerAgent。

    参数:
        http_client: httpx 异步客户端 fixture
    """
    with patch(
        "src.main.butler_agent.handle",
        new_callable=AsyncMock,
        return_value=AgentResponse(
            reply="群聊总结完成",
            data={"intent": "butler"},
        ),
    ) as mock_handle:
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "总结一下",
                "chat_type": "group",
                "chat_id": "chat-a",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "butler"
    assert body["confidence"] == 1.0
    assert body["response"] == "群聊总结完成"
    args, kwargs = mock_handle.await_args
    assert args[:3] == ("butler", "总结一下", "assle")
    assert isinstance(args[3], AsyncSession)
    assert kwargs == {"extra_state": {"chat_id": "chat-a", "chat_type": "group"}}
