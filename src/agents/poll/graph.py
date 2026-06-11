"""
PollAgent 图组装
构建群投票 StateGraph，负责创建、投票、查看和结束投票的全生命周期。

Workflow:
  START → classify_poll_intent
             ├─ create_poll   → create_poll_node   → END
             ├─ cast_vote     → cast_vote_node     → END
             ├─ view_results  → view_results_node  → END
             └─ end_poll      → end_poll_node      → END
"""
from langgraph.graph import END, START, StateGraph

from src.agents.poll.nodes import (
    cast_vote_node,
    classify_poll_intent,
    create_poll_node,
    end_poll_node,
    view_results_node,
)
from src.agents.poll.state import PollState
from src.graph.memory import checkpointer as _checkpointer
from src.schemas.response import AgentResponse


def _route_by_intent(state: dict) -> str:
    """根据意图选择下一个节点

    参数:
        state: 当前图状态

    返回:
        str: 下一个节点名
    """
    intent = state.get("intent", "")
    if intent in {"create_poll", "cast_vote", "view_results", "end_poll"}:
        return intent
    return "view_results"


class PollAgent:
    """群投票 agent，处理群聊 @ 机器人的投票相关请求"""

    def __init__(self, llm_client, scheduler_manager=None, webhook_client=None):
        """初始化 PollAgent 并编译 StateGraph

        参数:
            llm_client: LLMClient 实例
            scheduler_manager: SchedulerManager 实例，用于注册到期任务
            webhook_client: WebhookPushClient 实例，用于推送结果

        返回:
            None
        """
        self._llm = llm_client
        self._scheduler_manager = scheduler_manager
        self._webhook_client = webhook_client
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 PollAgent StateGraph

        参数:
            无

        返回:
            CompiledStateGraph: 编译后的 LangGraph 图
        """
        builder = StateGraph(PollState)
        builder.add_node("classify", classify_poll_intent)
        builder.add_node("create_poll", create_poll_node)
        builder.add_node("cast_vote", cast_vote_node)
        builder.add_node("view_results", view_results_node)
        builder.add_node("end_poll", end_poll_node)

        builder.add_edge(START, "classify")
        builder.add_conditional_edges(
            "classify",
            _route_by_intent,
            {
                "create_poll": "create_poll",
                "cast_vote": "cast_vote",
                "view_results": "view_results",
                "end_poll": "end_poll",
            },
        )
        builder.add_edge("create_poll", END)
        builder.add_edge("cast_vote", END)
        builder.add_edge("view_results", END)
        builder.add_edge("end_poll", END)

        return builder.compile(checkpointer=_checkpointer)

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理群投票相关请求

        参数:
            intent: 投票意图：create_poll / cast_vote / view_results / end_poll
            message: 用户原始消息
            user_id: 当前用户 ID
            db: SQLAlchemy 异步数据库会话
            extra_state: 额外上下文，需包含 chat_id

        返回:
            AgentResponse: 投票操作结果
        """
        extra_state = extra_state or {}
        initial_state = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "chat_id": extra_state.get("chat_id"),
        }
        config = {
            "configurable": {
                "db": db,
                "llm": self._llm,
                "scheduler_manager": self._scheduler_manager,
                "webhook_client": self._webhook_client,
                "thread_id": f"poll:{extra_state.get('chat_id') or user_id}",
            }
        }
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(
            reply=result.get("reply", "投票处理失败，请稍后再试。"),
            data=result.get("data"),
        )
