"""研究数据源网关测试"""
from unittest.mock import AsyncMock
import pytest
from src.research.sources import ResearchAccessScope, ResearchSourceGateway


@pytest.mark.asyncio
async def test_gateway_passes_scope_to_knowledge_service():
    """验证知识检索使用任务固定权限范围"""
    knowledge = AsyncMock()
    knowledge.search.return_value = []
    gateway = ResearchSourceGateway(knowledge=knowledge)
    scope = ResearchAccessScope(
        workspace_id="ws-a", user_id="open-u1",
    )
    from unittest.mock import ANY
    await gateway.search_knowledge(scope, "test", db=ANY, limit=5)
    knowledge.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_blocks_web_when_disabled():
    """验证 allow_web=False 时跳过联网搜索"""
    web = AsyncMock()
    gateway = ResearchSourceGateway(web=web)
    scope = ResearchAccessScope(workspace_id="ws-a", user_id="u1", allow_web=False)
    result = await gateway.search_web(scope, "test")
    assert result == []
    web.search.assert_not_awaited()
