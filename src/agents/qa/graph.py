from langgraph.graph import StateGraph, END
from src.agents.qa.state import QAState
from src.agents.qa.nodes import fetch_preferences, generate_qa_response, format_qa_response
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse
from src.graph.memory import checkpointer as _checkpointer


class QAAgent:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(QAState)
        builder.add_node("fetch_prefs", fetch_preferences)
        builder.add_node("generate", generate_qa_response)
        builder.add_node("format", format_qa_response)

        builder.set_entry_point("fetch_prefs")
        builder.add_edge("fetch_prefs", "generate")
        builder.add_edge("generate", "format")
        builder.add_edge("format", END)

        return builder.compile(checkpointer=_checkpointer)

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        initial_state: dict = {"intent": intent, "message": message, "user_id": user_id}
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
