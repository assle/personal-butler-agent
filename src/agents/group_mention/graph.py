"""
群聊 @ Agent 图组装
构建只允许群总结、天气查询和简单问答的受限群聊 StateGraph。
"""
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from src.agents.group_mention.nodes import (
    build_initial_messages,
    call_model_with_tools,
    classify_node,
    extract_tool_reply,
    route_by_category,
    simple_qa_node,
    summarize_group_node,
    unsupported_node,
    weather_placeholder_node,
)
from src.agents.group_mention.state import GroupMentionState
from src.agents.group_mention.tools import query_weather
from src.schemas.response import AgentResponse


class GroupMentionAgent:
    """群聊 @ 机器人场景 agent"""

    def __init__(self, llm_client, summary_agent, weather_service=None):
        """初始化群聊 @ agent

        参数:
            llm_client: LLM 客户端
            summary_agent: 群聊总结领域 agent
            weather_service: 天气服务；未注入时天气工具返回降级提示

        返回:
            None
        """
        self._llm = llm_client
        self._summary_agent = summary_agent
        self._weather_service = weather_service
        self._tools = [query_weather] if weather_service is not None else []
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
        if self._tools:
            builder.add_node("agent", call_model_with_tools)
            builder.add_node("tools", ToolNode(self._tools))
            builder.add_node("extract_tool_reply", extract_tool_reply)

        builder.add_edge(START, "classify")
        weather_route = "agent" if self._tools else "weather_placeholder"
        builder.add_conditional_edges(
            "classify",
            route_by_category,
            {
                "summarize_group": "summarize_group",
                "weather_placeholder": weather_route,
                "simple_qa": "simple_qa",
                "unsupported": "unsupported",
            },
        )
        builder.add_edge("summarize_group", END)
        builder.add_edge("weather_placeholder", END)
        builder.add_edge("simple_qa", END)
        builder.add_edge("unsupported", END)
        if self._tools:
            builder.add_conditional_edges(
                "agent",
                tools_condition,
                {"tools": "tools", END: "extract_tool_reply"},
            )
            builder.add_edge("tools", "agent")
            builder.add_edge("extract_tool_reply", END)
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
            "messages": build_initial_messages(message),
            "llm": self._llm,
            "summary_agent": self._summary_agent,
            "weather_service": self._weather_service,
            "db": db,
        }
        config = {
            "configurable": {
                "llm": self._llm,
                "tools": self._tools,
                "weather_service": self._weather_service,
                "thread_id": f"group_mention:{extra_state.get('chat_id') or user_id}",
            },
            "recursion_limit": 6,
        }
        try:
            result = await self._graph.ainvoke(initial_state, config)
            return AgentResponse(
                reply=result.get("reply", "") or "群聊回复生成失败，请稍后再试。",
                data=result.get("data"),
            )
        except GraphRecursionError:
            return AgentResponse(reply="天气查询工具调用次数过多，我先停一下，请补充更明确的地点。")
        except Exception:
            return AgentResponse(reply="群聊服务暂时不可用，请稍后再试。")
