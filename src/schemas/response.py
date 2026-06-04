"""
响应 Schema 定义
定义 Agent 内部响应（AgentResponse）

在总流程中的位置:
  agent.handle() → AgentResponse → callback 或 scheduler 适配层发送给外部通道
"""
from dataclasses import dataclass


@dataclass
class AgentResponse:
    """Agent 内部响应，由各 agent 的 handle() 方法返回"""

    reply: str
    """自然语言回复文本，显示给用户"""

    data: dict | None = None
    """可选结构化数据，如训练记录列表"""
