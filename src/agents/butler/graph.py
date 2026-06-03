"""
Butler Agent 图组装
构建小管家总控 LangGraph，支持 LLM 直接回复和工具调用循环

Workflow:
  START → agent(call_model) → tools_condition
  → tools → agent（有工具调用时循环）
  → extract_reply → END（无工具调用时输出最终回复）
"""
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from src.agents.butler.nodes import build_initial_messages, call_model, extract_reply
from src.agents.butler.state import ButlerState
from src.agents.butler.tools import ButlerToolContext, create_butler_tools
from src.graph.memory import checkpointer as _checkpointer
from src.memory.conversation import ConversationMemory
from src.schemas.response import AgentResponse


class ButlerAgent:
    """小管家总控 agent，负责用工具调用编排领域 agent 和检索服务"""

    def __init__(
        self,
        llm_client,
        fitness_agent,
        meal_agent,
        summary_agent,
        knowledge_service,
        web_search_service,
    ):
        """初始化 ButlerAgent 并编译工具调用图

        参数:
            llm_client: 支持 bind_tools().ainvoke() 和 chat() 的 LLM 客户端
            fitness_agent: 健身领域 agent
            meal_agent: 饮食领域 agent
            summary_agent: 摘要领域 agent
            knowledge_service: 本地知识库检索服务
            web_search_service: 联网搜索服务

        返回:
            None
        """
        self._llm = llm_client
        self._tool_context = ButlerToolContext(
            fitness_agent=fitness_agent,
            meal_agent=meal_agent,
            summary_agent=summary_agent,
            knowledge_service=knowledge_service,
            web_search_service=web_search_service,
        )
        self._tools = create_butler_tools(self._tool_context)
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 ButlerAgent StateGraph

        参数:
            无

        返回:
            CompiledStateGraph: 编译后的 LangGraph 图
        """
        builder = StateGraph(ButlerState)
        builder.add_node("agent", call_model)
        builder.add_node("tools", ToolNode(self._tools))
        builder.add_node("extract_reply", extract_reply)

        builder.add_edge(START, "agent")
        builder.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "tools", END: "extract_reply"},
        )
        builder.add_edge("tools", "agent")
        builder.add_edge("extract_reply", END)

        return builder.compile(checkpointer=_checkpointer)

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理用户消息并返回小管家回复

        参数:
            intent: 意图标识，通常为 "butler"
            message: 用户原始消息文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话
            extra_state: 可选聊天上下文，如 chat_type/chat_id

        返回:
            AgentResponse: 小管家自然语言回复和 intent 数据
        """
        chat_type = "single"
        chat_id = None
        if extra_state:
            chat_type = extra_state.get("chat_type", chat_type)
            chat_id = extra_state.get("chat_id", chat_id)

        memory = ConversationMemory(self._llm)
        summary, recent = await memory.get_context(user_id, db)

        initial_state: dict = {
            "messages": build_initial_messages(message),
            "user_id": user_id,
            "chat_type": chat_type,
            "chat_id": chat_id,
            "conversation_summary": summary,
            "recent_messages": recent,
        }
        config = {
            "configurable": {
                "db": db,
                "llm": self._llm,
                "tools": self._tools,
                "thread_id": f"butler:{user_id}",
                "user_id": user_id,
                "chat_type": chat_type,
                "chat_id": chat_id,
            },
            "recursion_limit": 8,
        }

        try:
            result = await self._graph.ainvoke(initial_state, config)
            reply = result.get("reply", "") or "我暂时没有生成有效回复。"
        except Exception:
            reply = "LLM 服务暂时不可用，请稍后重试。"

        await memory.save_exchange(user_id, message, reply, db)
        return AgentResponse(reply=reply, data={"intent": "butler"})
