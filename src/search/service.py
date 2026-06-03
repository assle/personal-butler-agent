"""
联网搜索服务
封装 Tavily HTTP 查询并输出统一 SearchResult 列表

Workflow:
1. 初始化时读取 Settings 中的联网搜索配置，可通过参数覆盖便于测试
2. search() 校验开关、密钥、查询文本和供应商
3. 调用 Tavily API 获取结果，失败时降级为空列表
4. 将供应商 JSON 响应归一化为 SearchResult
"""
import logging
from collections.abc import Awaitable, Callable

import httpx

from src.config import settings
from src.search.schemas import SearchResult


PostJson = Callable[[str, dict, int], Awaitable[dict]]

logger = logging.getLogger(__name__)


class WebSearchService:
    """联网搜索服务，负责按配置调用搜索供应商并归一化结果"""

    def __init__(
        self,
        enabled: bool | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        max_results: int | None = None,
        timeout_seconds: int | None = None,
        post_json: PostJson | None = None,
    ) -> None:
        """初始化联网搜索服务

        参数:
          enabled: 是否启用联网搜索；None 时读取全局配置
          provider: 搜索供应商名称；None 时读取全局配置
          api_key: 搜索供应商 API Key；None 时读取全局配置
          max_results: 最大返回条数；None 时读取全局配置
          timeout_seconds: HTTP 请求超时时间；None 时读取全局配置
          post_json: 可注入的异步 JSON POST 函数，便于测试替换真实 HTTP
        返回值:
          None
        """
        self._enabled = settings.web_search_enabled if enabled is None else enabled
        self._provider = settings.web_search_provider if provider is None else provider
        self._api_key = settings.web_search_api_key if api_key is None else api_key
        self._max_results = (
            settings.web_search_max_results if max_results is None else max_results
        )
        self._timeout_seconds = (
            settings.web_search_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self._post_json = post_json

    async def search(self, query: str) -> list[SearchResult]:
        """执行联网搜索并返回统一结果列表

        参数:
          query: 用户输入的搜索关键词
        返回值:
          SearchResult 列表；禁用、未配置、供应商不支持或 HTTP 失败时返回空列表
        """
        clean_query = query.strip()
        provider = self._provider.lower().strip()
        if (
            not self._enabled
            or not self._api_key
            or not clean_query
            or provider != "tavily"
        ):
            return []

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self._api_key,
            "query": clean_query,
            "max_results": self._max_results,
            "search_depth": "basic",
        }
        try:
            response = await self._post(url, payload, self._timeout_seconds)
        except httpx.HTTPError:
            logger.info("联网搜索 HTTP 请求失败，已降级为空结果", exc_info=True)
            return []

        return self._parse_results(response)

    async def _post(self, url: str, payload: dict, timeout: int) -> dict:
        """发送 JSON POST 请求

        参数:
          url: 请求地址
          payload: JSON 请求体
          timeout: 请求超时时间，单位秒
        返回值:
          响应 JSON 字典
        """
        if self._post_json is not None:
            return await self._post_json(url, payload, timeout)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    def _parse_results(self, response: dict) -> list[SearchResult]:
        """解析供应商响应为统一搜索结果

        参数:
          response: Tavily 返回的 JSON 字典
        返回值:
          最多 max_results 条 SearchResult
        """
        raw_results = response.get("results", [])
        if not isinstance(raw_results, list):
            return []

        results: list[SearchResult] = []
        for item in raw_results[: self._max_results]:
            if not isinstance(item, dict):
                continue
            score = item.get("score")
            results.append(
                SearchResult(
                    title=str(item.get("title", "")),
                    url=str(item.get("url", "")),
                    snippet=str(item.get("content", "")),
                    score=score if isinstance(score, int | float) else None,
                )
            )
        return results
