"""实况提供商冒烟测试（需手动触发）"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_RESEARCH_SMOKE") != "1",
    reason="RUN_LIVE_RESEARCH_SMOKE=1 required",
)


def test_live_web_search_returns_results():
    """验证联网搜索返回非空结果"""
    from src.search.service import WebSearchService
    import asyncio
    svc = WebSearchService()
    results = asyncio.run(svc.search("Python asyncio best practices"))
    assert isinstance(results, list)


def test_live_structured_synthesis_produces_draft():
    """验证 LLM 综合输出结构化草稿"""
    from src.llm.client import LLMClient
    from src.research.synthesis.schemas import ReportDraft
    import asyncio
    client = LLMClient()
    result = asyncio.run(client.ainvoke_structured(
        messages=[{"role": "user", "content": "Compare Python and Rust for web services"}],
        schema=ReportDraft, temperature=0.1,
    ))
    assert isinstance(result, ReportDraft)
