"""
LLM 客户端封装
基于 LangChain ChatOpenAI 封装 DeepSeek API 调用，提供 chat 和 chat_json 两种接口

在总流程中的位置:
  main.py 创建 LLMClient 单例 → 注入到 IntentRouter 和各 agent
  IntentRouter: chat_json 用于意图分类
  各 agent: chat 用于自然语言生成，chat_json 用于结构化数据提取

Workflow:
  所有 LLM 调用经过此客户端，统一管理 base_url、api_key、temperature 等参数
"""
from langchain_openai import ChatOpenAI
from src.config import settings


class LLMClient:
    """LLM 客户端，封装 DeepSeek API 的调用细节"""

    def __init__(self):
        """初始化 LLM 客户端，根据配置创建 ChatOpenAI 实例

        从 settings 读取 deepseek_model、api_key、base_url 等参数
        """
        self._model = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.7,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        """发送聊天消息，返回自然语言回复

        参数:
            messages: 消息列表，每条为 {"role": "system"|"user"|"assistant", "content": ...}
            model: 模型名称，默认使用 settings 中配置的模型
            temperature: 生成温度，0-1 之间，越高越随机

        返回:
            str: LLM 返回的自然语言文本，保证不为 None
        """
        response = await self._model.ainvoke(messages, temperature=temperature)
        content = response.content
        return content if content is not None else ""

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
    ) -> str:
        """发送聊天消息，返回 JSON 格式回复（使用更低温度提高一致性）

        与 chat 方法相同，但默认 temperature 更低，适用于结构化数据提取场景

        参数:
            messages: 消息列表
            model: 模型名称
            temperature: 生成温度，默认 0.3

        返回:
            str: LLM 返回的文本内容
        """
        return await self.chat(messages, model=model, temperature=temperature)
