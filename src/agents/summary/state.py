"""
Summary Agent 状态定义
定义 SummaryAgent StateGraph 中所有节点共享的状态字段

Workflow:
  - 私聊文本总结: 用户消息 → generate_summary → format_summary_response
  - 群聊消息总结: 触发消息 → summarize_group_messages → format_summary_response
  状态沿图逐步填充，最终输出格式化摘要
"""
from typing import TypedDict, Optional


class SummaryState(TypedDict, total=False):
    """群聊摘要 agent 的状态字典，包含执行过程中需要的所有字段"""

    intent: str
    """意图标识：summarize_text 或 summarize_group"""

    message: str
    """用户提供的待总结文本（私聊）或触发消息（群聊）"""

    user_id: str
    """用户唯一标识"""

    chat_id: str
    """群聊 ID，群聊总结时使用"""

    chat_type: str
    """会话类型："single"（私聊）或 "group"（群聊）"""

    reply: str
    """最终返回的结构化摘要文本"""

    error: Optional[str]
    """执行过程中的错误信息"""
