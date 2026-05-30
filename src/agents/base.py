from abc import ABC, abstractmethod
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


class BaseGraphAgent(ABC):
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    @abstractmethod
    async def handle(
        self, intent: str, message: str, user_id: str, db
    ) -> AgentResponse:
        ...
