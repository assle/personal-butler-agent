"""
Agent 抽象基类
定义所有 Agent 必须实现的 handle 接口，确保统一的调用方式

在总流程中的位置:
  意图路由 → AgentRegistry.get(intent) → agent.handle() → AgentResponse
  每个业务 agent 需继承此基类并通过 AgentRegistry 注册
"""
from abc import ABC, abstractmethod
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


class BaseGraphAgent(ABC):
    """Agent 抽象基类，所有 graph agent 的父类"""

    def __init__(self, llm_client: LLMClient):
        """初始化 agent，注入 LLM 客户端

        参数:
            llm_client: LangChain ChatOpenAI 封装，用于调用 DeepSeek 大模型
        """
        self._llm = llm_client

    @abstractmethod
    async def handle(
        self, intent: str, message: str, user_id: str, db
    ) -> AgentResponse:
        """处理用户消息，执行对应业务逻辑

        参数:
            intent: 意图分类结果（如 log_training / qa / today_plan 等）
            message: 用户原始消息文本
            user_id: 用户唯一标识（企业微信 OpenID 或调试用户 ID）
            db: SQLAlchemy 异步数据库会话，用于读写训练记录和用户偏好

        返回:
            AgentResponse: 包含回复文本和可选结构化数据的响应对象
        """
        ...
