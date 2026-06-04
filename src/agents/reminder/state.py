"""
Reminder Agent 状态定义
定义创建、查看和取消群 webhook 提醒时在 StateGraph 中传递的字段。

Workflow:
  PrivateButler 工具 → ReminderAgent.handle()
  → run_reminder_action → AgentResponse
"""
from typing import Any, TypedDict


class ReminderState(TypedDict, total=False):
    """提醒 agent 的状态字典，包含执行提醒操作所需字段"""

    intent: str
    """提醒操作意图：create_group_webhook_reminder/list_reminders/cancel_reminder"""

    message: str
    """用户原始消息或工具输入"""

    user_id: str
    """当前私聊用户 ID"""

    reply: str
    """最终返回给用户的自然语言回复"""

    data: dict[str, Any]
    """结构化结果数据"""

    error: str
    """执行过程中的错误信息"""
