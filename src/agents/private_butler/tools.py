"""
Butler 工具封装
把私聊可用的摘要、知识库、联网搜索、天气、提醒、翻译和记忆能力包装为 LangChain tools

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

from src.weather import format_weather_report
from src.agents.translate import translate_text
from src.agents.memory.service import MemoryService


@dataclass
class PrivateButlerToolContext:
    """Butler 工具依赖上下文，由应用 wiring 层注入"""

    # 摘要领域 agent，用于文本摘要和群聊摘要
    summary_agent: Any
    # 本地知识库服务，用于 scoped RAG 检索
    knowledge_service: Any
    # 联网搜索服务，用于外部网页检索
    web_search_service: Any
    # 天气服务，用于实时天气查询
    weather_service: Any = None
    # 提醒 agent，用于创建、查看和取消群 webhook 提醒
    reminder_agent: Any = None
    # 记忆服务，用于个性化记忆的增删改查和语义检索
    memory_service: Any = None


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


def _get_memory_service(context: PrivateButlerToolContext):
    """获取 memory service，未注入时返回 None

    参数:
        context: PrivateButlerToolContext 工具依赖上下文

    返回:
        MemoryService | None
    """
    return context.memory_service


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


def _weather_unavailable_message() -> str:
    """返回天气工具不可用提示

    参数:
        无

    返回:
        str: 缺少地点、服务或结果时的统一提示
    """
    return "天气功能已接入工具，但当前缺少明确地点，或天气数据源暂时查不到结果。请提供城市或地区，例如“今天上海天气”。"


def create_private_butler_tools(context: PrivateButlerToolContext) -> list[Any]:
    """创建 PrivateButlerAgent 可绑定的 LangChain 工具列表

    参数:
        context: PrivateButlerToolContext，包含领域 agent 与检索服务依赖

    返回:
        list[Any]: 十四个 LangChain tool，供模型工具调用使用
    """
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

    @tool
    async def query_weather(query: str) -> str:
        """查询指定地点的天气

        参数:
            query: 用户天气问题，应包含地点，可包含今天、明天或后天

        返回:
            str: 天气查询结果；地点不清或查询失败时返回提示
        """
        if context.weather_service is None:
            return _weather_unavailable_message()
        report = await context.weather_service.query(query)
        if report is None:
            return _weather_unavailable_message()
        return format_weather_report(report)

    @tool
    async def create_group_webhook_reminder(message: str) -> str:
        """创建最终发送到企业微信群 webhook 的提醒

        参数:
            message: 用户关于提醒时间、目标群和事项的完整原始描述

        返回:
            str: 提醒创建结果；缺少目标群或时间时返回说明
        """
        if context.reminder_agent is None:
            return "提醒功能尚未初始化，请先配置 scheduler target。"
        return await _call_agent(
            context.reminder_agent,
            "create_group_webhook_reminder",
            message,
        )

    @tool
    async def list_reminders(message: str) -> str:
        """查看当前用户创建的启用中提醒

        参数:
            message: 用户查看提醒的请求文本

        返回:
            str: 当前用户提醒列表
        """
        if context.reminder_agent is None:
            return "提醒功能尚未初始化，请先配置 scheduler target。"
        return await _call_agent(context.reminder_agent, "list_reminders", message)

    @tool
    async def cancel_reminder(message: str) -> str:
        """取消当前用户创建的指定提醒

        参数:
            message: 用户取消提醒的请求文本，应包含提醒编号

        返回:
            str: 取消结果
        """
        if context.reminder_agent is None:
            return "提醒功能尚未初始化，请先配置 scheduler target。"
        return await _call_agent(context.reminder_agent, "cancel_reminder", message)

    @tool
    async def translate(message: str) -> str:
        """将文本翻译成用户指定的目标语言

        参数:
            message: 用户的完整翻译请求，应包含目标语言和待翻译文本，例如"翻译成英文：今天天气很好"

        返回:
            str: 翻译后的文本
        """
        import re
        from langgraph.config import get_config

        configurable = get_config()["configurable"]
        llm = configurable["llm"]

        m = re.match(r"翻译(?:成|为|到)?\s*([a-zA-Z一-鿿]+)[：:]\s*(.+)", message, re.DOTALL)
        if m:
            target_lang = m.group(1).strip()
            text = m.group(2).strip()
        else:
            text = re.sub(r"^翻译(?:成|为|到)?\s*", "", message).strip()
            target_lang = "英文"

        return await translate_text(text=text, target_lang=target_lang, llm=llm)

    @tool
    async def add_memory(content: str) -> str:
        """添加一条关于用户的个性化记忆

        参数:
            content: 记忆内容，例如"用户不喝咖啡，偏好喝茶"

        返回:
            str: 添加结果
        """
        db, user_id, _, _ = _runtime()
        service = _get_memory_service(context)
        if service is None:
            return "记忆功能暂不可用。"
        memory = await service.add_memory(db, user_id, content, source="explicit")
        return f"已记住：{memory.content}"

    @tool
    async def list_memories(message: str = "") -> str:
        """查看当前用户的所有个性化记忆

        参数:
            message: 用户查看请求，可忽略

        返回:
            str: 记忆列表
        """
        db, user_id, _, _ = _runtime()
        service = _get_memory_service(context)
        if service is None:
            return "记忆功能暂不可用。"
        memories = await service.list_memories(db, user_id)
        if not memories:
            return "你还没有保存过记忆。可以跟我说"记住：xxx"来添加。"
        lines = [f"{i+1}. {m.content}" for i, m in enumerate(memories)]
        return "我记得以下关于你的信息：\n" + "\n".join(lines)

    @tool
    async def update_memory(memory_id: int, new_content: str) -> str:
        """更新一条个性化记忆

        参数:
            memory_id: 记忆编号（从 list_memories 获取）
            new_content: 新的记忆内容

        返回:
            str: 更新结果
        """
        db, user_id, _, _ = _runtime()
        service = _get_memory_service(context)
        if service is None:
            return "记忆功能暂不可用。"
        memory = await service.update_memory(db, memory_id, user_id, new_content)
        if memory is None:
            return f"没有找到编号为 {memory_id} 的记忆，或你没有权限修改。"
        return f"已更新：{memory.content}"

    @tool
    async def delete_memory(memory_id: int) -> str:
        """删除一条个性化记忆

        参数:
            memory_id: 记忆编号（从 list_memories 获取）

        返回:
            str: 删除结果
        """
        db, user_id, _, _ = _runtime()
        service = _get_memory_service(context)
        if service is None:
            return "记忆功能暂不可用。"
        ok = await service.delete_memory(db, memory_id, user_id)
        if not ok:
            return f"没有找到编号为 {memory_id} 的记忆，或你没有权限删除。"
        return f"已删除编号为 {memory_id} 的记忆。"

    @tool
    async def search_memory(query: str) -> str:
        """搜索与用户查询相关的个性化记忆

        参数:
            query: 要搜索的关键词或问题

        返回:
            str: 相关的记忆内容
        """
        db, user_id, _, _ = _runtime()
        service = _get_memory_service(context)
        if service is None:
            return "记忆功能暂不可用。"
        results = await service.search(db, user_id, query)
        if not results:
            return "没有找到相关记忆。"
        lines = [f"- {r['content']}" for r in results]
        return "相关记忆：\n" + "\n".join(lines)

    return [
        summarize_text,
        summarize_group_chat,
        search_local_knowledge,
        search_web,
        query_weather,
        create_group_webhook_reminder,
        list_reminders,
        cancel_reminder,
        translate,
        add_memory,
        list_memories,
        update_memory,
        delete_memory,
        search_memory,
    ]
