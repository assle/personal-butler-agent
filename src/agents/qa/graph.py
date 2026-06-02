"""
QA Agent - StateGraph 组装和 handle 入口
负责构建 QA StateGraph，获取用户偏好后注入 LLM prompt 实现个性化问答

在总流程中的位置:
  意图路由 → AgentRegistry.get("qa"|"unknown") → QAAgent
  → handle() 构建初始状态 → _graph.ainvoke() → AgentResponse
  QAAgent 同时作为回退 agent，处理 unknown 意图和通用对话

Workflow:
  fetch_preferences → retrieve_knowledge → generate_qa_response → format_qa_response
"""
from langgraph.graph import StateGraph, END
from src.agents.qa.state import QAState
from src.agents.qa.nodes import (
    fetch_preferences,
    retrieve_knowledge,
    generate_qa_response,
    format_qa_response,
)
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse
from src.memory.conversation import ConversationMemory
from src.graph.memory import checkpointer as _checkpointer


class QAAgent:
    """问答 agent，处理通用问答和回退意图，注入用户偏好提供个性化回复"""

    def __init__(self, llm_client: LLMClient):
        """初始化 QAAgent，构建并编译 StateGraph

        参数:
            llm_client: LangChain ChatOpenAI 封装实例
        """
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 QA StateGraph

        返回:
            CompiledStateGraph: 编译后的 LangGraph 状态图
        """
        builder = StateGraph(QAState)
        builder.add_node("fetch_prefs", fetch_preferences)
        builder.add_node("retrieve_knowledge", retrieve_knowledge)
        builder.add_node("generate", generate_qa_response)
        builder.add_node("format", format_qa_response)

        builder.set_entry_point("fetch_prefs")
        builder.add_edge("fetch_prefs", "retrieve_knowledge")
        builder.add_edge("retrieve_knowledge", "generate")
        builder.add_edge("generate", "format")
        builder.add_edge("format", END)

        return builder.compile(checkpointer=_checkpointer)

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识（"qa" 或 "unknown"）
            message: 用户原始消息文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话
            extra_state: 可选，路由层传入的 chat_type/chat_id 等额外上下文

        返回:
            AgentResponse: 包含个性化回复文本的响应
        """
        memory = ConversationMemory(self._llm)
        summary, recent = await memory.get_context(user_id, db)

        initial_state: dict = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "conversation_summary": summary,
            "recent_messages": recent,
            "chat_type": "single",
            "chat_id": None,
        }
        if extra_state:
            initial_state.update(extra_state)
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)

        reply = result.get("reply", "")
        await memory.save_exchange(user_id, message, reply, db)
        return AgentResponse(reply=reply, data=result.get("data"))
