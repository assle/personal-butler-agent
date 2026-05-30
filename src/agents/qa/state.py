"""
QA Agent 状态定义
定义 QAAgent StateGraph 中所有节点共享的状态字段

Workflow:
  用户消息 → fetch_preferences → generate_qa_response → format_qa_response
  获取用户偏好信息后，将其注入 LLM prompt 以提供个性化回复
"""
from typing import TypedDict, Optional


class QAState(TypedDict, total=False):
    """问答 agent 的状态字典，包含执行过程中需要的所有字段"""

    intent: str
    """意图标识：qa 或 unknown（回退路由）"""

    message: str
    """用户原始消息文本"""

    user_id: str
    """用户唯一标识"""

    preferences: dict
    """用户偏好摘要（fitness + meal），注入 system prompt 实现个性化"""

    reply: str
    """最终返回给用户的自然语言回复"""

    error: Optional[str]
    """执行过程中的错误信息"""
