"""
LLM 客户端测试
验证 LLMClient 正确封装 ChatOpenAI，chat 方法返回预期内容

测试范围:
  - chat 方法调用 ainvoke 并返回 AIMessage 内容
"""
import os
from unittest.mock import AsyncMock, patch
import pytest
from langchain_core.messages import AIMessage


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
