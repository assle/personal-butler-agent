"""
Reminder Agent 图组装
构建简单 StateGraph，负责创建、查看和取消群 webhook 提醒。

Workflow:
  START → run_reminder_action → END
"""
from langgraph.graph import END, START, StateGraph

from src.agents.reminder.nodes import run_reminder_action
from src.agents.reminder.state import ReminderState
from src.graph.memory import checkpointer as _checkpointer
from src.schemas.response import AgentResponse


class ReminderAgent:
    """提醒 agent，把私聊请求转换为最终群 webhook 推送任务"""

    def __init__(self, llm_client, reminder_service):
        """初始化 ReminderAgent 并编译 StateGraph

        参数:
            llm_client: LLMClient 实例
            reminder_service: ReminderService 实例

        返回:
            None
        """
        self._llm = llm_client
        self._reminder_service = reminder_service
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 ReminderAgent StateGraph

        参数:
            无

        返回:
            CompiledStateGraph: 编译后的 LangGraph 图
        """
        builder = StateGraph(ReminderState)
        builder.add_node("run", run_reminder_action)
        builder.add_edge(START, "run")
        builder.add_edge("run", END)
        return builder.compile(checkpointer=_checkpointer)

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理提醒相关请求

        参数:
            intent: create_group_webhook_reminder/list_reminders/cancel_reminder
            message: 用户原始消息或工具输入
            user_id: 当前私聊用户 ID
            db: SQLAlchemy 异步数据库会话
            extra_state: 可选额外状态，当前不使用

        返回:
            AgentResponse: 提醒操作结果
        """
        initial_state = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
        }
        config = {
            "configurable": {
                "db": db,
                "llm": self._llm,
                "reminder_service": self._reminder_service,
                "thread_id": f"reminder:{user_id}",
            }
        }
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(
            reply=result.get("reply", ""),
            data=result.get("data") or {"intent": intent},
        )
