"""
Fitness Agent 状态定义
定义 FitnessAgent StateGraph 中所有节点共享的状态字段

Workflow:
  用户消息 → extract → validate → persist → format_log（打卡路线）
           → fetch_history → fetch_prefs → generate → format_plan（计划路线）
  各节点通过 FitnessState 读写共享数据，状态字段随图执行逐步填充
"""
from typing import TypedDict, Optional


class FitnessState(TypedDict, total=False):
    """健身 agent 的状态字典，包含执行过程中需要的所有字段"""

    intent: str
    """意图标识：log_training 或 today_plan"""

    message: str
    """用户原始消息文本"""

    user_id: str
    """用户唯一标识"""

    raw_result: Optional[str]
    """LLM 提取训练记录的原始 JSON 字符串"""

    parsed_items: list[dict]
    """验证通过、即将入库的训练记录列表"""

    saved_records: list[dict]
    """已成功写入数据库的训练记录"""

    history_text: str
    """用户近一周训练记录的格式化文本"""

    preferences: dict
    """用户偏好设置（训练目标、身体数据等）"""

    reply: str
    """最终返回给用户的自然语言回复"""

    data: Optional[dict]
    """最终返回的结构化数据"""

    error: Optional[str]
    """执行过程中的错误信息，非空时触发错误处理节点"""
