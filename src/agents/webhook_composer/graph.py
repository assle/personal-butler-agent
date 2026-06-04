"""
Webhook 内容生成 Agent 图组装
构建 scheduler 专用 agent，用于生成最终群 markdown 正文，天气指令可调用天气工具。
"""
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from src.agents.webhook_composer.nodes import (
    build_initial_messages,
    call_model_with_tools,
    compose_webhook_body,
    extract_reply,
)
from src.agents.webhook_composer.state import WebhookComposerState
from src.agents.webhook_composer.tools import query_weather
from src.schemas.response import AgentResponse


class WebhookComposerAgent:
    """群 webhook 定时推送正文生成 agent"""

    def __init__(self, llm_client, weather_service=None):
        """初始化 WebhookComposerAgent

        参数:
            llm_client: LLM 客户端
            weather_service: 天气服务；未注入时保持简单 LLM 生成路径

        返回:
            None
        """
        self._llm = llm_client
        self._weather_service = weather_service
        self._weather_tool = query_weather if weather_service is not None else None
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建 StateGraph

        参数:
            无

        返回:
            CompiledStateGraph: 编译后的图
        """
        builder = StateGraph(WebhookComposerState)
        if self._weather_tool is None:
            builder.add_node("compose", compose_webhook_body)
            builder.add_edge(START, "compose")
            builder.add_edge("compose", END)
            return builder.compile()

        tools = [self._weather_tool]
        builder.add_node("agent", call_model_with_tools)
        builder.add_node("tools", ToolNode(tools))
        builder.add_node("extract_reply", extract_reply)
        builder.add_edge(START, "agent")
        builder.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "tools", END: "extract_reply"},
        )
        builder.add_edge("tools", "agent")
        builder.add_edge("extract_reply", END)
        return builder.compile()

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """生成群 webhook 推送正文

        参数:
            intent: 场景意图，通常为 webhook_compose
            message: scheduler target 配置指令
            user_id: 目标群或任务名称
            db: 数据库会话，当前不直接使用
            extra_state: chat_type/chat_id 等上下文

        返回:
            AgentResponse: 适合直接推送的 markdown 正文
        """
        extra_state = extra_state or {}
        initial_state = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "chat_type": extra_state.get("chat_type", "group"),
            "chat_id": extra_state.get("chat_id"),
            "llm": self._llm,
        }
        config = {}
        if self._weather_tool is not None:
            initial_state["messages"] = build_initial_messages(message)
            config = {
                "configurable": {
                    "llm": self._llm,
                    "tools": [self._weather_tool],
                    "weather_service": self._weather_service,
                    "thread_id": f"webhook_composer:{user_id}",
                },
                "recursion_limit": 6,
            }
        try:
            result = await self._graph.ainvoke(initial_state, config)
            return AgentResponse(
                reply=result.get("reply", "") or message,
                data={"intent": "webhook_compose"},
            )
        except GraphRecursionError:
            return AgentResponse(
                reply="天气查询工具调用次数过多，本次推送先暂停生成，请检查配置指令是否过于复杂。",
                data={"intent": "webhook_compose"},
            )
        except Exception:
            return AgentResponse(reply=message, data={"intent": "webhook_compose"})
