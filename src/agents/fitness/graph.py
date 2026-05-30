"""
Fitness Agent - StateGraph 组装和 handle 入口
负责构建 Fitness StateGraph，编排各节点之间的条件分支逻辑

在总流程中的位置:
  意图路由 → AgentRegistry.get("log_training"|"today_plan") → FitnessAgent
  → handle() 构建初始状态 → _graph.ainvoke() → AgentResponse

Workflow:
  入口根据 intent 分流：
    log_training → extract → validate → [persist → format_log] 或 error_handler
    today_plan   → fetch_history → fetch_prefs → generate → format_plan
    error        → error_handler
"""
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
    """健身 agent，支持训练打卡（log_training）和今日计划（today_plan）两种意图"""

    def __init__(self, llm_client: LLMClient):
        """初始化 FitnessAgent，构建并编译 StateGraph

        参数:
            llm_client: LangChain ChatOpenAI 封装实例
        """
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 Fitness StateGraph

        返回:
            CompiledStateGraph: 编译后的 LangGraph 状态图，挂载了 MemorySaver 检查点
        """
        builder = StateGraph(FitnessState)

        # log_training 路线节点
        builder.add_node("extract", extract_training_records)
        builder.add_node("validate", validate_records)
        builder.add_node("persist", persist_records)
        builder.add_node("format_log", format_log_response)

        # today_plan 路线节点
        builder.add_node("fetch_history", fetch_training_history)
        builder.add_node("fetch_prefs", fetch_user_preferences)
        builder.add_node("generate", generate_plan)
        builder.add_node("format_plan", format_plan_response)

        # 共享节点
        builder.add_node("error_handler", error_handler)

        # 入口路由：根据 intent 分流到不同的子路线
        builder.set_conditional_entry_point(
            path_condition,
            {
                "log_training": "extract",
                "today_plan": "fetch_history",
                "error_handler": "error_handler",
            },
        )

        # log_training 子图：extract → validate → [persist → format_log] 或 error_handler
        builder.add_edge("extract", "validate")
        builder.add_conditional_edges(
            "validate",
            log_path_condition,
            {"persist": "persist", "error_handler": "error_handler"},
        )
        builder.add_edge("persist", "format_log")
        builder.add_edge("format_log", END)

        # today_plan 子图：fetch_history → fetch_prefs → generate → format_plan
        builder.add_edge("fetch_history", "fetch_prefs")
        builder.add_edge("fetch_prefs", "generate")
        builder.add_edge("generate", "format_plan")
        builder.add_edge("format_plan", END)

        # 错误处理
        builder.add_edge("error_handler", END)

        return builder.compile(checkpointer=_checkpointer)

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识（"log_training" 或 "today_plan"）
            message: 用户原始消息文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话

        返回:
            AgentResponse: 包含自然语言回复和可选结构化数据的响应
        """
        initial_state: dict = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
        }
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
