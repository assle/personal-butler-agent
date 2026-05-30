"""
Meal Agent - StateGraph 组装和 handle 入口
负责构建 Meal StateGraph，编排节点之间的线性执行流程

在总流程中的位置:
  意图路由 → AgentRegistry.get("make_meal_plan") → MealAgent
  → handle() 构建初始状态 → _graph.ainvoke() → AgentResponse

Workflow:
  fetch_preferences → check_training_today → generate_meal_plan → format_meal_response
  线性执行，前一节点输出作为后一节点输入
"""
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
from src.graph.memory import checkpointer as _checkpointer


class MealAgent:
    """饮食 agent，根据用户偏好和训练状态生成一日三餐食谱"""

    def __init__(self, llm_client: LLMClient):
        """初始化 MealAgent，构建并编译 StateGraph

        参数:
            llm_client: LangChain ChatOpenAI 封装实例
        """
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 Meal StateGraph

        返回:
            CompiledStateGraph: 编译后的 LangGraph 状态图
        """
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

        return builder.compile(checkpointer=_checkpointer)

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识（"make_meal_plan"）
            message: 用户原始消息文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话

        返回:
            AgentResponse: 包含一日三餐食谱文本的响应
        """
        initial_state: dict = {"intent": intent, "message": message, "user_id": user_id}
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
