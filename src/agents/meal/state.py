"""
Meal Agent 状态定义
定义 MealAgent StateGraph 中所有节点共享的状态字段

Workflow:
  用户消息 → fetch_preferences → check_training_today → generate_meal_plan → format_meal_response
  状态沿线性图逐步填充，最终输出食谱文本
"""
from typing import TypedDict, Optional


class MealState(TypedDict, total=False):
    """饮食 agent 的状态字典，包含执行过程中需要的所有字段"""

    intent: str
    """意图标识：make_meal_plan"""

    message: str
    """用户原始消息文本"""

    user_id: str
    """用户唯一标识"""

    preferences: dict
    """用户饮食偏好（热量目标、饮食类型、过敏原等）"""

    trained_today: bool
    """用户今天是否有训练记录，影响蛋白质比例"""

    reply: str
    """最终返回给用户的一日三餐食谱文本"""

    data: Optional[dict]
    """最终返回的结构化数据"""

    error: Optional[str]
    """执行过程中的错误信息"""

    conversation_summary: Optional[str]
    """早期对话的压缩摘要文本"""

    recent_messages: list[dict]
    """最近6轮对话消息列表"""
