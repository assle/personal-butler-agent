"""
LLM 客户端测试
验证 LLMClient 正确封装 ChatOpenAI，chat 方法返回预期内容

测试范围:
  - chat 方法调用 ainvoke 并返回 AIMessage 内容
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel


@pytest.mark.asyncio
async def test_llm_client_chat_returns_content():
    """验证 LLMClient.chat() 正确调用 ChatOpenAI 并返回消息内容

    模拟 ChatOpenAI 构造和 ainvoke 调用，确保 chat 方法透传结果。
    """
    mock_message = AIMessage(content="Hello, I am an AI.")

    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        with patch("src.llm.client.ChatOpenAI") as mock_chat_openai_cls:
            mock_model = AsyncMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_message)
            mock_chat_openai_cls.return_value = mock_model

            from src.llm.client import LLMClient

            llm = LLMClient()
            result = await llm.chat(
                messages=[{"role": "user", "content": "Hi"}],
            )
            assert result == "Hello, I am an AI."


@pytest.mark.asyncio
async def test_llm_client_ainvoke_messages_returns_message_object():
    """验证 LLMClient.ainvoke_messages() 返回原始 LangChain 消息对象

    返回:
        None；通过断言确认工具调用场景可以保留 AIMessage 元数据
    """
    mock_message = AIMessage(content="final answer")

    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        with patch("src.llm.client.ChatOpenAI") as mock_chat_openai_cls:
            mock_model = AsyncMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_message)
            mock_chat_openai_cls.return_value = mock_model

            from src.llm.client import LLMClient

            llm = LLMClient()
            result = await llm.ainvoke_messages(
                messages=[{"role": "user", "content": "Hi"}],
            )

            assert result is mock_message
            mock_model.ainvoke.assert_awaited_once()


def test_llm_client_bind_tools_delegates_to_chat_model():
    """验证 LLMClient.bind_tools() 透传到底层 ChatOpenAI 实例

    返回:
        None；通过断言确认 private tool-calling agent 可以获取绑定工具后的 runnable
    """
    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        with patch("src.llm.client.ChatOpenAI") as mock_chat_openai_cls:
            mock_model = MagicMock()
            bound_model = object()
            mock_model.bind_tools.return_value = bound_model
            mock_chat_openai_cls.return_value = mock_model

            from src.llm.client import LLMClient

            llm = LLMClient()
            tools = [lambda query: query]
            result = llm.bind_tools(tools)

            assert result is bound_model
            mock_model.bind_tools.assert_called_once_with(tools)


class _FakePlanDraft(BaseModel):
    objective: str = ""
    steps: list = []


@pytest.mark.asyncio
async def test_ainvoke_structured_returns_validated_model():
    """验证结构化调用通过 DeepSeek 兼容的函数调用返回模型；无参数；无返回值。"""
    from src.llm.client import LLMClient

    client = LLMClient()
    fake_model = MagicMock()
    structured_runnable = AsyncMock()
    structured_runnable.ainvoke.return_value = _FakePlanDraft(
        objective="compare",
        steps=[],
    )
    fake_model.with_structured_output.return_value = structured_runnable
    client._model = fake_model
    result = await client.ainvoke_structured(
        messages=[{"role": "user", "content": "compare"}],
        schema=_FakePlanDraft,
        temperature=0.1,
    )
    assert isinstance(result, _FakePlanDraft)
    assert result.objective == "compare"
    fake_model.with_structured_output.assert_called_once_with(
        _FakePlanDraft,
        method="function_calling",
        tool_choice="required",
    )


@pytest.mark.asyncio
async def test_ainvoke_structured_retries_empty_provider_result_once():
    """验证结构化接口收到空结果时重试一次；无参数；无返回值。"""
    from src.llm.client import LLMClient

    client = LLMClient()
    fake_model = MagicMock()
    structured_runnable = AsyncMock()
    structured_runnable.ainvoke.side_effect = [
        None,
        _FakePlanDraft(objective="retry-success", steps=[]),
    ]
    fake_model.with_structured_output.return_value = structured_runnable
    client._model = fake_model

    result = await client.ainvoke_structured(
        messages=[{"role": "user", "content": "compare"}],
        schema=_FakePlanDraft,
    )

    assert result.objective == "retry-success"
    assert structured_runnable.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_ainvoke_structured_rejects_repeated_empty_provider_result():
    """验证结构化接口连续为空时抛出明确错误；无参数；无返回值。"""
    from src.llm.client import LLMClient

    client = LLMClient()
    fake_model = MagicMock()
    structured_runnable = AsyncMock()
    structured_runnable.ainvoke.return_value = None
    fake_model.with_structured_output.return_value = structured_runnable
    client._model = fake_model

    with pytest.raises(RuntimeError, match="结构化输出为空"):
        await client.ainvoke_structured(
            messages=[{"role": "user", "content": "compare"}],
            schema=_FakePlanDraft,
        )

    assert structured_runnable.ainvoke.await_count == 2
