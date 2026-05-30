from langgraph.graph import StateGraph, END
from src.agents.summary.state import SummaryState
from src.agents.summary.nodes import generate_summary, format_summary_response
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse
from src.graph.memory import checkpointer as _checkpointer


class SummaryAgent:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(SummaryState)
        builder.add_node("generate", generate_summary)
        builder.add_node("format", format_summary_response)
        builder.set_entry_point("generate")
        builder.add_edge("generate", "format")
        builder.add_edge("format", END)
        return builder.compile(checkpointer=_checkpointer)

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        initial_state: dict = {"intent": intent, "message": message, "user_id": user_id}
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
