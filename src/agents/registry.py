from typing import Protocol, runtime_checkable
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


@runtime_checkable
class GraphAgent(Protocol):
    async def handle(
        self, intent: str, message: str, user_id: str, db
    ) -> AgentResponse: ...


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, GraphAgent] = {}
        self._fallback: GraphAgent | None = None

    def register(self, intent: str, agent: GraphAgent):
        self._agents[intent] = agent

    def set_fallback(self, agent: GraphAgent):
        self._fallback = agent

    def get(self, intent: str) -> GraphAgent | None:
        return self._agents.get(intent, self._fallback)
