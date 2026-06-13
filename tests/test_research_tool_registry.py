"""研究工具注册表测试"""
from unittest.mock import AsyncMock, Mock
import pytest
from src.research.tools.schemas import (
    ResearchToolDefinition,
    ToolExecutionContext,
    ToolExecutionResult,
)
from src.research.tools.registry import (
    DuplicateResearchToolError,
    ResearchToolDeniedError,
    ResearchToolRegistry,
)


def _ctx() -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_id="ws-a", user_id="u1", task_id="R1", step_id="R1:1:a",
    )


def test_registry_rejects_duplicate_tool_names():
    """验证工具名称不可重复注册"""
    registry = ResearchToolRegistry()
    registry.register(ResearchToolDefinition(name="knowledge.search"))
    with pytest.raises(DuplicateResearchToolError):
        registry.register(ResearchToolDefinition(name="knowledge.search"))


@pytest.mark.asyncio
async def test_registry_checks_permission_before_provider_call():
    """验证工具执行前先经过权限引擎"""
    from src.governance.permissions import PermissionDecision, PermissionEffect
    permission = Mock()
    permission.evaluate.return_value = PermissionDecision(
        effect=PermissionEffect.DENY, policy_id="test", reason="blocked",
    )
    provider = AsyncMock()
    registry = ResearchToolRegistry(permission_engine=permission)
    registry.register(ResearchToolDefinition(name="web.search"), provider=provider)
    result = await registry.execute(AsyncMock(), _ctx(), "web.search", {"query": "x"})
    assert result.success is False
    provider.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_registry_executes_provider_and_returns_result():
    """验证正常路径：权限通过后执行提供者"""
    from src.governance.permissions import PermissionDecision, PermissionEffect
    permission = Mock()
    permission.evaluate.return_value = PermissionDecision(
        effect=PermissionEffect.ALLOW, policy_id="test", reason="ok",
    )
    provider = AsyncMock()
    provider.execute.return_value = ToolExecutionResult(success=True, data={"result": "ok"})
    registry = ResearchToolRegistry(permission_engine=permission)
    registry.register(ResearchToolDefinition(name="knowledge.search"), provider=provider)
    result = await registry.execute(AsyncMock(), _ctx(), "knowledge.search", {"query": "test"})
    assert result.success is True
    provider.execute.assert_awaited_once()


def test_registry_lists_registered_tools():
    """验证 list_tools 返回所有已注册工具"""
    registry = ResearchToolRegistry()
    registry.register(ResearchToolDefinition(name="knowledge.search"))
    registry.register(ResearchToolDefinition(name="web.search"))
    tools = registry.list_tools()
    assert {t.name for t in tools} == {"knowledge.search", "web.search"}


@pytest.mark.asyncio
async def test_registry_passes_database_session_to_provider():
    """验证注册表把当前数据库会话传给工具提供者"""
    db = AsyncMock()
    provider = AsyncMock()
    provider.execute.return_value = ToolExecutionResult(success=True, data={"result": "ok"})
    registry = ResearchToolRegistry()
    registry.register(ResearchToolDefinition(name="knowledge.search"), provider=provider)

    result = await registry.execute(db, _ctx(), "knowledge.search", {"query": "test"})
    assert result.success is True
    provider.execute.assert_awaited_once_with(db, _ctx(), {"query": "test"})


@pytest.mark.asyncio
async def test_open_circuit_blocks_provider():
    """验证熔断器打开时阻止提供者执行"""
    from unittest.mock import AsyncMock
    breaker = AsyncMock()
    breaker.allow.return_value = False
    provider = AsyncMock()
    registry = ResearchToolRegistry(circuit_breaker=breaker)
    registry.register(ResearchToolDefinition(name="web.search"), provider=provider)
    result = await registry.execute(AsyncMock(), _ctx(), "web.search", {"query": "x"})
    assert result.success is False
    assert "circuit_open" in result.error
    provider.execute.assert_not_awaited()
