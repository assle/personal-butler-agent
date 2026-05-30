from langgraph.graph import StateGraph, END
from src.agents.fitness.state import FitnessState
from src.agents.fitness.nodes import (
    extract_training_records,
    validate_records,
    persist_records,
    format_log_response,
    fetch_training_history,
    fetch_user_preferences,
    generate_plan,
    format_plan_response,
    path_condition,
    log_path_condition,
    error_handler,
)
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse
from src.graph.memory import checkpointer as _checkpointer


class FitnessAgent:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(FitnessState)

        # log_training path nodes
        builder.add_node("extract", extract_training_records)
        builder.add_node("validate", validate_records)
        builder.add_node("persist", persist_records)
        builder.add_node("format_log", format_log_response)

        # today_plan path nodes
        builder.add_node("fetch_history", fetch_training_history)
        builder.add_node("fetch_prefs", fetch_user_preferences)
        builder.add_node("generate", generate_plan)
        builder.add_node("format_plan", format_plan_response)

        # shared nodes
        builder.add_node("error_handler", error_handler)

        # entry routing
        builder.set_conditional_entry_point(
            path_condition,
            {
                "log_training": "extract",
                "today_plan": "fetch_history",
                "error_handler": "error_handler",
            },
        )

        # log_training subgraph
        builder.add_edge("extract", "validate")
        builder.add_conditional_edges(
            "validate",
            log_path_condition,
            {"persist": "persist", "error_handler": "error_handler"},
        )
        builder.add_edge("persist", "format_log")
        builder.add_edge("format_log", END)

        # today_plan subgraph
        builder.add_edge("fetch_history", "fetch_prefs")
        builder.add_edge("fetch_prefs", "generate")
        builder.add_edge("generate", "format_plan")
        builder.add_edge("format_plan", END)

        # error handler
        builder.add_edge("error_handler", END)

        return builder.compile(checkpointer=_checkpointer)

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        initial_state: dict = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
        }
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
