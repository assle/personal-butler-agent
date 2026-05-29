from openai import AsyncOpenAI
from src.config import settings


class LLMClient:
    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=model or settings.deepseek_model,
            messages=messages,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        return content if content is not None else ""

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
    ) -> str:
        """Chat with lower temperature, suitable for structured/JSON output."""
        return await self.chat(messages, model=model, temperature=temperature)
