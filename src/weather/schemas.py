"""
天气数据结构
定义天气服务对外返回的统一结果对象

Workflow:
1. service 解析 Open-Meteo 响应
2. 将地点、日期、温度、降雨和风速整理为 WeatherReport
3. 调用方只依赖 WeatherReport，不直接处理外部 API JSON
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class WeatherReport:
    """统一天气查询结果对象"""

    # 展示用地点名称
    location_name: str
    # 目标日期，格式为 YYYY-MM-DD
    date: str
    # 天气现象中文描述
    condition: str
    # 当前温度；查询非今日时可能为空
    temperature_c: float | None
    # 当日最高温
    max_temperature_c: float | None
    # 当日最低温
    min_temperature_c: float | None
    # 降水概率百分比
    precipitation_probability: float | None
    # 风速，单位 km/h
    wind_speed_kmh: float | None
