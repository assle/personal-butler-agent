"""
Summary Agent - StateGraph 组装和 handle 入口
负责构建 Summary StateGraph，将文本/群聊消息总结为结构化摘要

在总流程中的位置:
  意图路由 → AgentRegistry.get("summarize_text") 或 AgentRegistry.get("summarize_group")
  → SummaryAgent.handle() 构建初始状态 → _graph.ainvoke() → AgentResponse

Workflow:
  chat_type="group" → summarize_group_messages → format_summary_response
  chat_type="single" → generate_summary → format_summary_response
"""
from langgraph.graph import StateGraph, END, START
from src.agents.summary.state import SummaryState
from src.agents.summary.nodes import (
    generate_summary,
    summarize_group_messages,
    format_summary_response,
)
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse
from src.graph.memory import checkpointer as _checkpointer


def _route_by_chat_type(state: dict) -> str:
    """根据会话类型路由到不同的总结节点

    参数:
        state: 当前图状态

    返回:
        str: 下一个节点名——"summarize_group" 或 "generate"
    """
    if state.get("chat_type") == "group":
        return "summarize_group"
    return "generate"


class SummaryAgent:
    """群聊摘要 agent，支持私聊文本总结和群聊消息总结两种模式"""

    def __init__(self, llm_client: LLMClient):
        """初始化 SummaryAgent，构建并编译 StateGraph

        参数:
            llm_client: LangChain ChatOpenAI 封装实例
        """
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 Summary StateGraph

        返回:
            CompiledStateGraph: 编译后的 LangGraph 状态图
        """
        builder = StateGraph(SummaryState)
        builder.add_node("generate", generate_summary)
        builder.add_node("summarize_group", summarize_group_messages)
        builder.add_node("format", format_summary_response)

        builder.add_conditional_edges(START, _route_by_chat_type, {
            "summarize_group": "summarize_group",
            "generate": "generate",
        })
        builder.add_edge("summarize_group", "format")
        builder.add_edge("generate", "format")
        builder.add_edge("format", END)
        return builder.compile(checkpointer=_checkpointer)

    async def handle(
        self, intent: str, message: str, user_id: str, db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识（"summarize_text" 或 "summarize_group"）
            message: 用户消息文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话
            extra_state: 可选，额外状态字段（群聊场景传入 chat_id, chat_type 等）

        返回:
            AgentResponse: 包含结构化摘要文本的响应
        """
        initial_state: dict = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
        }
        if extra_state:
            initial_state.update(extra_state)
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
