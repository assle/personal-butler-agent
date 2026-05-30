from langgraph.graph import StateGraph, END
from src.agents.meal.state import MealState
from src.agents.meal.nodes import (
    fetch_preferences,
    check_training_today,
    generate_meal_plan,
    format_meal_response,
)
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


class MealAgent:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(MealState)
        builder.add_node("fetch_prefs", fetch_preferences)
        builder.add_node("check_training", check_training_today)
        builder.add_node("generate", generate_meal_plan)
        builder.add_node("format", format_meal_response)

        builder.set_entry_point("fetch_prefs")
        builder.add_edge("fetch_prefs", "check_training")
        builder.add_edge("check_training", "generate")
        builder.add_edge("generate", "format")
        builder.add_edge("format", END)

        return builder.compile()

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        initial_state: dict = {"intent": intent, "message": message, "user_id": user_id}
        config = {"configurable": {"db": db, "llm": self._llm}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
