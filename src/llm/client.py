from langchain_openai import ChatOpenAI
from src.config import settings


class LLMClient:
    def __init__(self):
        self._model = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.7,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        response = await self._model.ainvoke(messages, temperature=temperature)
        content = response.content
        return content if content is not None else ""

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
    ) -> str:
        return await self.chat(messages, model=model, temperature=temperature)
