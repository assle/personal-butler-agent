"""
联网搜索服务测试
验证 WebSearchService 在关闭、成功和 HTTP 异常场景下的行为

测试范围:
  - 默认关闭或禁用时不发起 HTTP 请求并返回空列表
  - Tavily 响应被归一化为 SearchResult
  - malformed 响应结构降级为空列表
  - HTTP 请求失败时降级为空列表且不抛异常
"""
import httpx
import pytest

from src.search import WebSearchService


@pytest.mark.asyncio
async def test_search_returns_empty_when_disabled_without_calling_post_json():
    """验证关闭联网搜索时直接返回空列表

    输入参数为普通查询文本；返回值应为空列表，并且不会调用注入的 post_json 函数。
    """
    called = False

    async def post_json(url: str, payload: dict, timeout: int) -> dict:
        nonlocal called
        called = True
        return {}

    service = WebSearchService(
        enabled=False,
        provider="tavily",
        api_key="tvly-test",
        max_results=3,
        timeout_seconds=6,
        post_json=post_json,
    )

    results = await service.search("今天北京天气")

    assert results == []
    assert called is False


@pytest.mark.asyncio
async def test_search_tavily_success_normalizes_results():
    """验证 Tavily 成功响应会被归一化为 SearchResult

    输入参数为查询文本；返回值应包含标题、链接、摘要和分数字段，并校验请求 URL、payload 与超时时间。
    """
    calls = []

    async def post_json(url: str, payload: dict, timeout: int) -> dict:
        calls.append((url, payload, timeout))
        return {
            "results": [
                {
                    "title": "北京天气",
                    "url": "https://example.com/weather",
                    "content": "北京今天晴，气温适中。",
                    "score": 0.91,
                },
                {
                    "title": "多余结果",
                    "url": "https://example.com/extra",
                    "content": "不应超过 max_results。",
                    "score": 0.2,
                },
            ]
        }

    service = WebSearchService(
        enabled=True,
        provider="tavily",
        api_key="tvly-test",
        max_results=1,
        timeout_seconds=6,
        post_json=post_json,
    )

    results = await service.search("今天北京天气")

    assert len(results) == 1
    assert results[0].title == "北京天气"
    assert results[0].url == "https://example.com/weather"
    assert results[0].snippet == "北京今天晴，气温适中。"
    assert results[0].score == 0.91
    assert calls == [
        (
            "https://api.tavily.com/search",
            {
                "api_key": "tvly-test",
                "query": "今天北京天气",
                "max_results": 1,
                "search_depth": "basic",
            },
            6,
        )
    ]


@pytest.mark.asyncio
async def test_search_http_error_returns_empty_list():
    """验证 HTTP 请求失败时降级为空列表

    输入参数为普通查询文本；当底层 post_json 抛出 httpx.HTTPError 时，返回值应为空列表且不继续抛出。
    """
    calls = 0

    async def post_json(url: str, payload: dict, timeout: int) -> dict:
        nonlocal calls
        calls += 1
        raise httpx.HTTPError("network failed")

    service = WebSearchService(
        enabled=True,
        provider="tavily",
        api_key="tvly-test",
        max_results=3,
        timeout_seconds=6,
        post_json=post_json,
    )

    results = await service.search("今天北京天气")

    assert results == []
    assert calls == 1


@pytest.mark.asyncio
async def test_search_malformed_response_returns_empty_list():
    """验证供应商返回非字典结构时降级为空列表

    输入参数为普通查询文本；当底层 post_json 返回 list 等异常结构时，返回值应为空列表且不抛异常。
    """

    async def post_json(url: str, payload: dict, timeout: int) -> list[str]:
        return ["bad"]

    service = WebSearchService(
        enabled=True,
        provider="tavily",
        api_key="tvly-test",
        max_results=3,
        timeout_seconds=6,
        post_json=post_json,
    )

    results = await service.search("今天北京天气")

    assert results == []
