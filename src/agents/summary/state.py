"""
Summary Agent 状态定义
定义 SummaryAgent StateGraph 中所有节点共享的状态字段

Workflow:
  用户消息 → generate_summary → format_summary_response
  状态沿线性图逐步填充，最终输出格式化群聊摘要
"""
from typing import TypedDict, Optional


class SummaryState(TypedDict, total=False):
    """群聊摘要 agent 的状态字典，包含执行过程中需要的所有字段"""

    intent: str
    """意图标识：summarize_text"""

    message: str
    """用户提供的群聊记录文本（待总结内容）"""

    user_id: str
    """用户唯一标识"""

    reply: str
    """最终返回的结构化摘要文本"""

    error: Optional[str]
    """执行过程中的错误信息"""
