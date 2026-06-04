"""
群聊 @ Agent 图组装
构建只允许群总结、天气占位和简单问答的受限群聊 StateGraph。
"""
from langgraph.graph import END, START, StateGraph

from src.agents.group_mention.nodes import (
    classify_node,
    route_by_category,
    simple_qa_node,
    summarize_group_node,
    unsupported_node,
    weather_placeholder_node,
)
from src.agents.group_mention.state import GroupMentionState
from src.schemas.response import AgentResponse


class GroupMentionAgent:
    """群聊 @ 机器人场景 agent"""

    def __init__(self, llm_client, summary_agent):
        """初始化群聊 @ agent

        参数:
            llm_client: LLM 客户端
            summary_agent: 群聊总结领域 agent

        返回:
            None
        """
        self._llm = llm_client
        self._summary_agent = summary_agent
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建群聊 @ StateGraph

        参数:
            无

        返回:
            CompiledStateGraph: 编译后的图
        """
        builder = StateGraph(GroupMentionState)
        builder.add_node("classify", classify_node)
        builder.add_node("summarize_group", summarize_group_node)
        builder.add_node("weather_placeholder", weather_placeholder_node)
        builder.add_node("simple_qa", simple_qa_node)
        builder.add_node("unsupported", unsupported_node)

        builder.add_edge(START, "classify")
        builder.add_conditional_edges(
            "classify",
            route_by_category,
            {
                "summarize_group": "summarize_group",
                "weather_placeholder": "weather_placeholder",
                "simple_qa": "simple_qa",
                "unsupported": "unsupported",
            },
        )
        builder.add_edge("summarize_group", END)
        builder.add_edge("weather_placeholder", END)
        builder.add_edge("simple_qa", END)
        builder.add_edge("unsupported", END)
        return builder.compile()

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理群聊 @ 消息

        参数:
            intent: 场景意图，通常为 group_mention
            message: 群聊消息文本
            user_id: 发送者用户 ID
            db: 数据库会话
            extra_state: chat_type/chat_id 等群聊上下文

        返回:
            AgentResponse: 群聊回复
        """
        extra_state = extra_state or {}
        initial_state = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "chat_type": extra_state.get("chat_type", "group"),
            "chat_id": extra_state.get("chat_id"),
            "llm": self._llm,
            "summary_agent": self._summary_agent,
            "db": db,
        }
        try:
            result = await self._graph.ainvoke(initial_state)
            return AgentResponse(
                reply=result.get("reply", "") or "群聊回复生成失败，请稍后再试。",
                data=result.get("data"),
            )
        except Exception:
            return AgentResponse(reply="群聊服务暂时不可用，请稍后再试。")
