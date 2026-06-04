"""
天气查询服务
封装 Open-Meteo 地理编码和天气预报查询，并把自然语言天气问题转成统一结果

Workflow:
1. query() 清洗用户问题，提取地点和目标日期偏移
2. _geocode() 调用 Open-Meteo geocoding 获取经纬度
3. _forecast() 调用 Open-Meteo forecast 获取当前天气和未来预报
4. _parse_report() 生成 WeatherReport，调用失败时返回 None
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

import httpx

from src.config import settings
from src.weather.schemas import WeatherReport


GetJson = Callable[[str, dict, int], Awaitable[object]]

logger = logging.getLogger(__name__)

_TIME_WORDS = (
    "今天",
    "今日",
    "现在",
    "当前",
    "此刻",
    "明天",
    "明日",
    "后天",
    "未来",
)
_WEATHER_WORDS = (
    "天气",
    "气温",
    "温度",
    "下雨",
    "降雨",
    "会不会",
    "怎么样",
    "如何",
    "查询",
    "查一下",
    "帮我查",
    "请问",
)
_PUNCTUATION_PATTERN = re.compile(r"[，。！？、,.!?；;：:\s]+")


class WeatherService:
    """天气服务，负责调用 Open-Meteo 并归一化天气查询结果"""

    def __init__(
        self,
        timeout_seconds: int | None = None,
        get_json: GetJson | None = None,
    ) -> None:
        """初始化天气服务

        参数:
            timeout_seconds: HTTP 请求超时时间；None 时读取全局配置
            get_json: 可注入的异步 JSON GET 函数，便于测试或离线替换真实 HTTP

        返回:
            None
        """
        self._timeout_seconds = (
            settings.weather_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self._get_json = get_json

    async def query(self, query: str) -> WeatherReport | None:
        """查询天气并返回统一天气结果

        参数:
            query: 用户自然语言天气问题，至少应包含地点

        返回:
            WeatherReport | None: 查询成功返回天气结果；地点不清或接口失败返回 None
        """
        clean_query = query.strip()
        if not clean_query:
            return None

        location = self._extract_location(clean_query)
        if not location:
            return None

        try:
            geocode = await self._geocode(location)
            if geocode is None:
                return None
            forecast = await self._forecast(geocode["latitude"], geocode["longitude"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.info("天气查询请求或响应解析失败，已降级为空结果", exc_info=True)
            return None

        return self._parse_report(
            location_name=geocode["name"],
            query=clean_query,
            forecast=forecast,
        )

    def _extract_location(self, query: str) -> str:
        """从天气问题中提取地点文本

        参数:
            query: 用户自然语言天气问题

        返回:
            str: 提取到的地点；无法判断时返回空字符串
        """
        compact = _PUNCTUATION_PATTERN.sub("", query)
        for word in _TIME_WORDS + _WEATHER_WORDS:
            compact = compact.replace(word, "")
        compact = compact.strip()
        compact = re.sub(r"^(我想知道|想知道|帮我|我要|给我)", "", compact)
        compact = re.sub(r"(穿什么|带伞吗|适合出门吗|适合运动吗)$", "", compact)
        return compact.strip()

    async def _geocode(self, location: str) -> dict | None:
        """调用 Open-Meteo 地理编码接口

        参数:
            location: 地点关键词

        返回:
            dict | None: 包含 name/latitude/longitude 的地点对象；无匹配返回 None
        """
        response = await self._get(
            "https://geocoding-api.open-meteo.com/v1/search",
            {
                "name": location,
                "count": 1,
                "language": "zh",
                "format": "json",
            },
            self._timeout_seconds,
        )
        if not isinstance(response, dict):
            return None
        results = response.get("results")
        if not isinstance(results, list) or not results:
            return None
        first = results[0]
        if not isinstance(first, dict):
            return None

        name = str(first.get("name", location))
        country = str(first.get("country", "")).strip()
        admin = str(first.get("admin1", "")).strip()
        location_name = "，".join(part for part in (name, admin, country) if part)
        return {
            "name": location_name or location,
            "latitude": float(first["latitude"]),
            "longitude": float(first["longitude"]),
        }

    async def _forecast(self, latitude: float, longitude: float) -> object:
        """调用 Open-Meteo 天气预报接口

        参数:
            latitude: 纬度
            longitude: 经度

        返回:
            object: 解码后的天气预报 JSON 对象
        """
        return await self._get(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": ",".join(
                    [
                        "temperature_2m",
                        "relative_humidity_2m",
                        "apparent_temperature",
                        "precipitation",
                        "weather_code",
                        "wind_speed_10m",
                    ]
                ),
                "daily": ",".join(
                    [
                        "weather_code",
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_probability_max",
                    ]
                ),
                "timezone": "auto",
                "forecast_days": 7,
            },
            self._timeout_seconds,
        )

    async def _get(self, url: str, params: dict, timeout: int) -> object:
        """发送 HTTP GET 请求并解析 JSON

        参数:
            url: 请求地址
            params: URL 查询参数
            timeout: 请求超时时间，单位秒

        返回:
            object: 解码后的 JSON 响应
        """
        if self._get_json is not None:
            return await self._get_json(url, params, timeout)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    def _parse_report(
        self,
        location_name: str,
        query: str,
        forecast: object,
    ) -> WeatherReport | None:
        """把 Open-Meteo forecast 响应解析成 WeatherReport

        参数:
            location_name: 展示用地点名称
            query: 用户原始天气问题，用于判断今天/明天/后天
            forecast: forecast API 返回对象

        返回:
            WeatherReport | None: 解析成功返回天气结果；数据不足返回 None
        """
        if not isinstance(forecast, dict):
            return None

        daily = forecast.get("daily")
        if not isinstance(daily, dict):
            return None

        day_index = self._target_day_index(query)
        dates = daily.get("time", [])
        codes = daily.get("weather_code", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        precip_probs = daily.get("precipitation_probability_max", [])
        if not isinstance(dates, list) or day_index >= len(dates):
            return None

        current = forecast.get("current")
        current_temp = None
        wind_speed = None
        if day_index == 0 and isinstance(current, dict):
            current_temp = self._optional_float(current.get("temperature_2m"))
            wind_speed = self._optional_float(current.get("wind_speed_10m"))

        return WeatherReport(
            location_name=location_name,
            date=str(dates[day_index]),
            condition=self._weather_code_to_text(self._list_get(codes, day_index)),
            temperature_c=current_temp,
            max_temperature_c=self._optional_float(self._list_get(max_temps, day_index)),
            min_temperature_c=self._optional_float(self._list_get(min_temps, day_index)),
            precipitation_probability=self._optional_float(
                self._list_get(precip_probs, day_index)
            ),
            wind_speed_kmh=wind_speed,
        )

    def _target_day_index(self, query: str) -> int:
        """判断用户查询的是未来第几天

        参数:
            query: 用户原始天气问题

        返回:
            int: 0 表示今天，1 表示明天，2 表示后天
        """
        if "后天" in query:
            return 2
        if "明天" in query or "明日" in query:
            return 1
        return 0

    def _weather_code_to_text(self, code: object) -> str:
        """把 Open-Meteo weather_code 转成中文天气描述

        参数:
            code: Open-Meteo 天气代码

        返回:
            str: 中文天气描述
        """
        mapping = {
            0: "晴",
            1: "大部晴朗",
            2: "局部多云",
            3: "阴",
            45: "雾",
            48: "雾凇",
            51: "小毛毛雨",
            53: "毛毛雨",
            55: "较强毛毛雨",
            56: "冻毛毛雨",
            57: "较强冻毛毛雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            66: "冻雨",
            67: "较强冻雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            77: "雪粒",
            80: "小阵雨",
            81: "阵雨",
            82: "强阵雨",
            85: "小阵雪",
            86: "强阵雪",
            95: "雷暴",
            96: "雷暴伴小冰雹",
            99: "雷暴伴较强冰雹",
        }
        try:
            return mapping.get(int(code), "未知天气")
        except (TypeError, ValueError):
            return "未知天气"

    def _list_get(self, items: object, index: int) -> object:
        """安全读取列表元素

        参数:
            items: 可能是列表的对象
            index: 目标下标

        返回:
            object: 下标存在时返回元素，否则返回 None
        """
        if isinstance(items, list) and index < len(items):
            return items[index]
        return None

    def _optional_float(self, value: object) -> float | None:
        """把可选数值转换为 float

        参数:
            value: 外部 API 返回的原始数值

        返回:
            float | None: 可转换时返回 float，否则返回 None
        """
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
