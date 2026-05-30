"""
Agent 注册表
维护 intent（意图）到 Agent 实例的映射，提供统一的 agent 查找入口

在总流程中的位置:
  意图路由确定 intent 后，通过 AgentRegistry.get(intent) 获取对应 agent，
  再调用 agent.handle() 执行业务逻辑。所有 agent 在 main.py 中完成注册。
"""
from typing import Protocol, runtime_checkable
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


@runtime_checkable
class GraphAgent(Protocol):
    """Graph Agent 协议，定义 agent 必须实现的 handle 接口"""

    async def handle(
        self, intent: str, message: str, user_id: str, db
    ) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识
            message: 用户消息
            user_id: 用户标识
            db: 数据库会话

        返回:
            AgentResponse: 处理结果
        """
        ...


class AgentRegistry:
    """Agent 注册表，管理 intent → agent 的映射关系"""

    def __init__(self):
        """初始化注册表，创建空的 agent 映射和回退 agent"""
        self._agents: dict[str, GraphAgent] = {}
        self._fallback: GraphAgent | None = None

    def register(self, intent: str, agent: GraphAgent):
        """注册一个 agent 到指定意图

        参数:
            intent: 意图标识字符串（如 "log_training", "qa"）
            agent: 实现了 GraphAgent 协议的 agent 实例
        """
        self._agents[intent] = agent

    def set_fallback(self, agent: GraphAgent):
        """设置回退 agent，当意图未找到对应 agent 时使用

        参数:
            agent: 作为回退的 agent 实例（通常为 QA agent）
        """
        self._fallback = agent

    def get(self, intent: str) -> GraphAgent | None:
        """根据意图查找对应的 agent

        参数:
            intent: 意图标识字符串

        返回:
            GraphAgent | None: 匹配的 agent 实例，未找到时返回回退 agent
        """
        return self._agents.get(intent, self._fallback)
