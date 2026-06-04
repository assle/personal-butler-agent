"""
天气查询包入口
对外导出天气服务、天气结果数据结构和天气结果格式化函数

Workflow:
1. WeatherService 从自然语言查询中提取地点和目标日期
2. 调用 Open-Meteo 地理编码和天气预报接口
3. format_weather_report() 把结构化结果转换为中文回复文本
"""
from src.weather.formatting import format_weather_report
from src.weather.schemas import WeatherReport
from src.weather.service import WeatherService

__all__ = ["WeatherReport", "WeatherService", "format_weather_report"]
