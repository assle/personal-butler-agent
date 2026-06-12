"""
群聊 @ 工具封装
定义群聊受限场景允许调用的 LangChain tools。

Workflow:
1. GroupMentionAgent 在 LangGraph config 中注入 weather_service 和 knowledge_service
2. query_weather 读取服务并查询天气
3. add_to_knowledge 读取服务并将内容存入群知识库
4. 工具结果回到群聊 LLM，由模型生成最终群聊回复
"""
from langchain_core.tools import tool
from langgraph.config import get_config

from src.weather import format_weather_report


def _weather_unavailable_message() -> str:
    """返回天气工具不可用提示

    参数:
        无

    返回:
        str: 缺少地点、服务或结果时的统一提示
    """
    return '天气功能已接入工具，但当前缺少明确地点，或天气数据源暂时查不到结果。请提供城市或地区，例如"今天上海天气"。'


@tool
async def query_weather(query: str) -> str:
    """查询指定地点的天气

    参数:
        query: 群聊中的天气问题，应包含地点，可包含今天、明天或后天

    返回:
        str: 天气查询结果；地点不清或查询失败时返回提示
    """
    weather_service = get_config().get("configurable", {}).get("weather_service")
    if weather_service is None:
        return _weather_unavailable_message()
    report = await weather_service.query(query)
    if report is None:
        return _weather_unavailable_message()
    return format_weather_report(report)


@tool
async def add_to_knowledge(content: str, title: str = "") -> str:
    """将内容存放到当前群聊的知识库

    当用户在群聊中说"把这个加到群知识库"、"帮群存一下这个"时调用。
    内容会自动设置为群聊范围内可见。

    参数:
        content: 要存入知识库的文本内容
        title: 可选标题，为空时自动截取内容前 40 字符

    返回:
        str: 入库结果
    """
    from src.knowledge.schemas import KnowledgeIngestRequest
    configurable = get_config().get("configurable", {})
    db = configurable.get("db")
    knowledge_service = configurable.get("knowledge_service")
    if knowledge_service is None:
        return "知识库服务暂不可用。"
    if db is None:
        return "数据库连接不可用。"
    chat_id = configurable.get("chat_id", "")
    user_id = configurable.get("user_id", "")
    title_text = title.strip() or content.strip()[:40]
    try:
        request = KnowledgeIngestRequest(
            title=title_text,
            source=f"chat://group/{chat_id}",
            content=content.strip(),
            scope_type="group",
            scope_id=chat_id,
            domain="qa",
        )
        doc = await knowledge_service.ingest(request, db)
        if doc is None:
            return "该内容已存在于群知识库中，跳过重复导入。"
        return f"已添加到群知识库：\"{title_text}\""
    except Exception as e:
        return f"知识库添加失败：{e}"
