"""
PollAgent 状态定义
定义群投票创建、投票、查看和结束时在 StateGraph 中传递的字段。

Workflow:
  GroupMentionAgent → PollAgent.handle()
  → StateGraph 节点 → AgentResponse
"""
from typing import Any

from typing_extensions import TypedDict


class PollState(TypedDict, total=False):
    """投票 agent 状态字典"""

    intent: str
    """投票操作意图：create_poll / cast_vote / view_results / end_poll"""

    message: str
    """用户原始消息"""

    user_id: str
    """当前用户 ID"""

    chat_id: str | None
    """群聊 ID"""

    reply: str
    """最终返回给用户的自然语言回复"""

    data: dict[str, Any]
    """结构化结果数据，如投票统计"""

    error: str
    """执行过程中的错误信息"""
