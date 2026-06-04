"""
Webhook 内容生成 Agent 图组装
构建 scheduler 专用 agent，用于生成最终群 markdown 正文。
"""
from langgraph.graph import END, START, StateGraph

from src.agents.webhook_composer.nodes import compose_webhook_body
from src.agents.webhook_composer.state import WebhookComposerState
from src.schemas.response import AgentResponse


class WebhookComposerAgent:
    """群 webhook 定时推送正文生成 agent"""

    def __init__(self, llm_client):
        """初始化 WebhookComposerAgent

        参数:
            llm_client: LLM 客户端

        返回:
            None
        """
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建 StateGraph

        参数:
            无

        返回:
            CompiledStateGraph: 编译后的图
        """
        builder = StateGraph(WebhookComposerState)
        builder.add_node("compose", compose_webhook_body)
        builder.add_edge(START, "compose")
        builder.add_edge("compose", END)
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
        try:
            result = await self._graph.ainvoke(initial_state)
            return AgentResponse(
                reply=result.get("reply", "") or message,
                data={"intent": "webhook_compose"},
            )
        except Exception:
            return AgentResponse(reply=message, data={"intent": "webhook_compose"})
