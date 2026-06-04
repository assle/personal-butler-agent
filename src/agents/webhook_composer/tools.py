"""
Webhook Composer 工具封装
定义定时推送正文生成场景允许调用的 LangChain tools。

Workflow:
1. WebhookComposerAgent 在 LangGraph config 中注入 weather_service
2. query_weather 工具读取服务并查询天气
3. 工具结果回到 composer LLM，由模型生成最终群 markdown 正文
"""
from langchain_core.tools import tool
from langgraph.config import get_config

from src.weather.formatting import format_weather_report


def _weather_unavailable_message() -> str:
    """返回天气工具不可用提示

    参数:
        无

    返回:
        str: 缺少地点、服务或结果时的统一提示
    """
    return "天气功能已接入工具，但当前缺少明确地点，或天气数据源暂时查不到结果。请提供城市或地区，例如“今天上海天气”。"


@tool
async def query_weather(query: str) -> str:
    """查询指定地点的天气

    参数:
        query: 推送配置中的天气问题，应包含地点，可包含今天、明天或后天

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
