"""研究 Specialist 测试"""
from unittest.mock import AsyncMock
import pytest
from src.research.specialists.fetch import WebFetchResearcher
from src.research.specialists.knowledge import KnowledgeResearcher
from src.research.specialists.web import WebResearcher
from src.research.tools.schemas import ToolExecutionContext


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(workspace_id="ws-a", user_id="u1", task_id="R1", step_id="R1:1:a")


@pytest.mark.asyncio
async def test_knowledge_specialist_returns_evidence():
    """验证知识 Specialist 返回证据"""
    from dataclasses import dataclass

    @dataclass
    class FakeResult:
        source: str = "test.md"
        title: str = "Test Doc"
        content: str = "some content"

    gateway = AsyncMock()
    gateway.search_knowledge.return_value = [FakeResult()]
    specialist = KnowledgeResearcher(gateway)
    result = await specialist.execute(AsyncMock(), _ctx(), {"query": "test"})
    assert result.success is True
    assert "找到 1 条" in result.data["summary"]


@pytest.mark.asyncio
async def test_web_specialist_preserves_url():
    """验证网页证据保留 URL"""
    from dataclasses import dataclass

    @dataclass
    class FakeResult:
        url: str = "http://example.com"
        title: str = "Example"
        snippet: str = "some snippet"
        confidence: float = 0.8

    web_service = AsyncMock()
    web_service.search.return_value = [FakeResult()]
    specialist = WebResearcher(web_service)
    result = await specialist.execute(AsyncMock(), _ctx(), {"query": "test"})
    assert result.success is True


@pytest.mark.asyncio
async def test_web_specialist_marks_failure():
    """验证搜索故障被明确标记而不是伪造结果"""
    web_service = AsyncMock()
    web_service.search.side_effect = RuntimeError("provider down")
    specialist = WebResearcher(web_service)
    result = await specialist.execute(AsyncMock(), _ctx(), {"query": "test"})
    assert result.success is False
    assert "联网检索失败" in result.error


@pytest.mark.asyncio
async def test_web_fetch_specialist_uses_url_as_query_fallback():
    """验证仅提供 URL 时抓取证据仍有非空查询；无参数；无返回值。"""
    fetcher = AsyncMock()
    fetcher.fetch.return_value = "page content"
    specialist = WebFetchResearcher(fetcher)

    result = await specialist.execute(
        AsyncMock(),
        _ctx(),
        {"url": "https://example.com/paper"},
    )

    assert result.success is True
    assert result.data["evidence"][0]["query"] == "https://example.com/paper"
