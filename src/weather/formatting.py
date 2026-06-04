"""
天气结果格式化工具
把 WeatherReport 转换为可直接回复用户或注入 LLM 的中文文本。

Workflow:
1. WeatherService 返回结构化 WeatherReport
2. format_weather_report() 统一格式化温度、降水概率和风速
3. 场景 agent 或 LangChain tool 复用该文本格式
"""
from src.weather.schemas import WeatherReport


def _format_number(value: float | None, suffix: str) -> str:
    """格式化可选数字字段

    参数:
        value: 可选数字
        suffix: 数字单位

    返回:
        str: 带单位的文本；无值时返回“未知”
    """
    if value is None:
        return "未知"
    if value.is_integer():
        return f"{int(value)}{suffix}"
    return f"{value:.1f}{suffix}"


def format_weather_report(report: WeatherReport) -> str:
    """格式化天气查询结果

    参数:
        report: WeatherService 返回的统一天气结果

    返回:
        str: 适合用户阅读的中文天气回复
    """
    current = ""
    if report.temperature_c is not None:
        current = f"当前 {_format_number(report.temperature_c, '°C')}，"
    wind = ""
    if report.wind_speed_kmh is not None:
        wind = f"，风速 {_format_number(report.wind_speed_kmh, ' km/h')}"
    return (
        f"{report.location_name} {report.date} 天气：{report.condition}，"
        f"{current}最高 {_format_number(report.max_temperature_c, '°C')}，"
        f"最低 {_format_number(report.min_temperature_c, '°C')}，"
        f"降水概率 {_format_number(report.precipitation_probability, '%')}{wind}。"
    )
