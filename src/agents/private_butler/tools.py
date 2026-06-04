"""
Butler 工具封装
把已有领域 agent、知识库服务和联网搜索服务包装为 LangChain tools

Workflow:
  create_private_butler_tools(context) 接收运行期单例依赖
  → 每个 tool 只暴露模型可填写的业务文本参数
  → _runtime() 从 LangGraph/LangChain config 读取 db/user/chat 上下文
  → tool 调用已有 agent 或 service 并返回可读文本
"""
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import tool
from langgraph.config import get_config


@dataclass
class PrivateButlerToolContext:
    """Butler 工具依赖上下文，由应用 wiring 层注入"""

    # 健身领域 agent，用于训练打卡和今日训练计划
    fitness_agent: Any
    # 饮食领域 agent，用于生成一日三餐计划
    meal_agent: Any
    # 摘要领域 agent，用于文本摘要和群聊摘要
    summary_agent: Any
    # 本地知识库服务，用于 scoped RAG 检索
    knowledge_service: Any
    # 联网搜索服务，用于外部网页检索
    web_search_service: Any


def _runtime():
    """读取当前工具调用的运行时上下文

    参数:
        无；通过 langgraph.config.get_config() 读取当前 Runnable config

    返回:
        tuple: (db, user_id, chat_type, chat_id)
    """
    configurable = get_config().get("configurable", {})
    db = configurable.get("db")
    user_id = configurable.get("user_id")
    chat_type = configurable.get("chat_type", "single")
    chat_id = configurable.get("chat_id")
    return db, user_id, chat_type, chat_id


async def _call_agent(agent: Any, intent: str, message: str) -> str:
    """调用领域 agent 并返回回复文本

    参数:
        agent: 具备 handle() 方法的领域 agent
        intent: 要传给 agent 的意图名称
        message: 用户原始消息或工具输入文本

    返回:
        str: agent 生成的 reply；空结果时返回兜底提示
    """
    db, user_id, chat_type, chat_id = _runtime()
    result = await agent.handle(
        intent,
        message,
        user_id,
        db,
        extra_state={"chat_type": chat_type, "chat_id": chat_id},
    )
    return result.reply or "该工具没有生成有效结果。"


def _format_knowledge_results(results: list[Any]) -> str:
    """格式化本地知识库检索结果

    参数:
        results: KnowledgeService.search() 返回的片段结果列表

    返回:
        str: 适合注入给 PrivateButlerAgent 的可读文本
    """
    if not results:
        return "本地知识库没有查到相关资料。"
    return "\n\n".join(
        f"[{index}] {result.title} - {result.source}\n{result.content}"
        for index, result in enumerate(results, start=1)
    )


def _format_web_results(results: list[Any]) -> str:
    """格式化联网搜索结果

    参数:
        results: WebSearchService.search() 返回的 SearchResult 列表

    返回:
        str: 适合展示给用户或注入上下文的搜索摘要文本
    """
    if not results:
        return "联网搜索没有查到结果，或当前未启用联网搜索。"
    return "\n\n".join(
        f"[{index}] {result.title}\nURL: {result.url}\n摘要: {result.snippet}"
        for index, result in enumerate(results, start=1)
    )


def create_private_butler_tools(context: PrivateButlerToolContext) -> list[Any]:
    """创建 PrivateButlerAgent 可绑定的 LangChain 工具列表

    参数:
        context: PrivateButlerToolContext，包含领域 agent 与检索服务依赖

    返回:
        list[Any]: 七个 LangChain tool，供模型工具调用使用
    """

    @tool
    async def log_training(message: str) -> str:
        """记录用户的一次训练打卡

        参数:
            message: 用户描述训练内容的原始文本

        返回:
            str: 健身 agent 生成的训练记录回复
        """
        return await _call_agent(context.fitness_agent, "log_training", message)

    @tool
    async def get_today_training_plan(message: str) -> str:
        """根据用户历史和偏好生成今日训练计划

        参数:
            message: 用户关于今日训练计划的请求文本

        返回:
            str: 健身 agent 生成的今日训练计划
        """
        return await _call_agent(context.fitness_agent, "today_plan", message)

    @tool
    async def make_meal_plan(message: str) -> str:
        """根据用户需求和偏好生成一日三餐计划

        参数:
            message: 用户关于饮食计划的请求文本

        返回:
            str: 饮食 agent 生成的餐食计划
        """
        return await _call_agent(context.meal_agent, "make_meal_plan", message)

    @tool
    async def summarize_text(text: str) -> str:
        """总结用户提供的一段文本内容

        参数:
            text: 需要摘要的原始文本

        返回:
            str: 摘要 agent 生成的文本摘要
        """
        return await _call_agent(context.summary_agent, "summarize_text", text)

    @tool
    async def summarize_group_chat(message: str) -> str:
        """总结当前群聊上下文中的最近聊天内容

        参数:
            message: 用户触发群聊摘要的请求文本

        返回:
            str: 摘要 agent 生成的群聊摘要
        """
        return await _call_agent(context.summary_agent, "summarize_group", message)

    @tool
    async def search_local_knowledge(query: str) -> str:
        """搜索当前用户或群聊可见的本地知识库

        参数:
            query: 用户要检索的关键词或问题

        返回:
            str: 格式化后的本地知识库片段；无结果时返回提示
        """
        db, user_id, chat_type, chat_id = _runtime()
        results = await context.knowledge_service.search(
            query=query,
            user_id=user_id,
            db=db,
            chat_type=chat_type,
            chat_id=chat_id,
            domains=["global", "qa"],
            limit=5,
        )
        return _format_knowledge_results(results)

    @tool
    async def search_web(query: str) -> str:
        """使用联网搜索服务查询外部网页资料

        参数:
            query: 用户要联网检索的关键词或问题

        返回:
            str: 格式化后的联网搜索结果；无结果或未启用时返回提示
        """
        results = await context.web_search_service.search(query)
        return _format_web_results(results)

    return [
        log_training,
        get_today_training_plan,
        make_meal_plan,
        summarize_text,
        summarize_group_chat,
        search_local_knowledge,
        search_web,
    ]
