"""
响应 Schema 定义
定义 Agent 内部响应（AgentResponse）和 API 外发响应（DebugMessageResponse）

在总流程中的位置:
  agent.handle() → AgentResponse → router 转换为 DebugMessageResponse → JSON 返回客户端
"""
from dataclasses import dataclass, field
from pydantic import BaseModel


@dataclass
class AgentResponse:
    """Agent 内部响应，由各 agent 的 handle() 方法返回"""

    reply: str
    """自然语言回复文本，显示给用户"""

    data: dict | None = None
    """可选结构化数据，如训练记录列表"""


class DebugMessageResponse(BaseModel):
    """调试消息 API 响应 Schema"""

    intent: str
    """意图分类结果"""

    confidence: float
    """意图置信度 0.0-1.0"""

    response: str
    """处理后的回复文本"""

    data: dict | None = None
    """可选结构化数据"""
