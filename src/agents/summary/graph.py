"""
Summary Agent - StateGraph 组装和 handle 入口
负责构建 Summary StateGraph，将群聊文本总结为结构化摘要

在总流程中的位置:
  意图路由 → AgentRegistry.get("summarize_text") → SummaryAgent
  → handle() 构建初始状态 → _graph.ainvoke() → AgentResponse

Workflow:
  generate_summary → format_summary_response
  最简单的线性图，无需数据库访问
"""
from langgraph.graph import StateGraph, END
from src.agents.summary.state import SummaryState
from src.agents.summary.nodes import generate_summary, format_summary_response
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse
from src.graph.memory import checkpointer as _checkpointer


class SummaryAgent:
    """群聊摘要 agent，将群聊记录总结为包含主题、结论、待办、决策的结构化摘要"""

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
        builder.add_node("format", format_summary_response)
        builder.set_entry_point("generate")
        builder.add_edge("generate", "format")
        builder.add_edge("format", END)
        return builder.compile(checkpointer=_checkpointer)

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识（"summarize_text"）
            message: 待总结的群聊文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话（本 agent 未使用）

        返回:
            AgentResponse: 包含结构化摘要文本的响应
        """
        initial_state: dict = {"intent": intent, "message": message, "user_id": user_id}
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
