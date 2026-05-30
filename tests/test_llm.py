import os
from unittest.mock import AsyncMock, patch
import pytest
from langchain_core.messages import AIMessage


@pytest.mark.asyncio
async def test_llm_client_chat_returns_content():
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
