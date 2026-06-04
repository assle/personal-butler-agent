"""
LLM 客户端封装
基于 LangChain ChatOpenAI 封装 DeepSeek API 调用，提供 chat、chat_json 和工具调用接口

在总流程中的位置:
  main.py 创建 LLMClient 单例 → 注入到领域 agent 和 scene agent
  GroupMentionAgent: chat_json 可用于群聊消息兜底分类
  各 agent: chat 用于自然语言生成，chat_json 用于结构化数据提取
  PrivateButlerAgent: bind_tools/ainvoke_messages 用于工具绑定和保留 AIMessage 元数据

Workflow:
  所有 LLM 调用经过此客户端，统一管理 base_url、api_key、temperature 等参数
"""
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
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

    def bind_tools(self, tools: list[Any]) -> Runnable:
        """绑定工具到当前聊天模型，并返回 LangChain runnable

        参数:
            tools: LangChain 支持的工具定义列表，例如 callable、BaseTool 或 schema

        返回:
            Runnable: 底层 ChatOpenAI 绑定工具后的可调用对象
        """
        return self._model.bind_tools(tools)

    async def ainvoke_messages(
        self,
        messages: list[dict[str, str]] | list[BaseMessage],
        *,
        tools: list[Any] | None = None,
        temperature: float = 0.7,
    ) -> BaseMessage:
        """发送消息并返回原始 LangChain 消息对象

        参数:
            messages: 字典消息列表或 BaseMessage 消息列表
            tools: 可选工具列表；提供时先绑定到底层模型再调用
            temperature: 生成温度，0-1 之间，越高越随机

        返回:
            BaseMessage: LLM 返回的原始消息对象，保留 tool_calls 等元数据
        """
        model = self.bind_tools(tools) if tools is not None else self._model
        return await model.ainvoke(messages, temperature=temperature)

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
        response = await self.ainvoke_messages(messages, temperature=temperature)
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
