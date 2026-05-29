import os
from unittest.mock import AsyncMock, patch
import pytest
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice


@pytest.mark.asyncio
async def test_llm_client_chat_returns_content():
    mock_completion = ChatCompletion(
        id="test-id",
        model="deepseek-chat",
        created=1234567890,
        object="chat.completion",
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant", content="Hello, I am an AI."
                ),
                finish_reason="stop",
            )
        ],
    )

    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        with patch("src.llm.client.AsyncOpenAI") as mock_openai_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
            mock_openai_cls.return_value = mock_client

            from src.llm.client import LLMClient

            llm = LLMClient()
            result = await llm.chat(
                messages=[{"role": "user", "content": "Hi"}],
                model="deepseek-chat",
            )
            assert result == "Hello, I am an AI."
