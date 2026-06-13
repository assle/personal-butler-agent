"""Provider 注册测试"""
import pytest
from src.research.tools.registry import ResearchToolRegistry
from src.research.providers.builtin import BuiltinResearchDependencies, register_builtin_research_tools


def test_builtin_provider_registers_expected_tools():
    from unittest.mock import AsyncMock
    registry = ResearchToolRegistry()
    deps = BuiltinResearchDependencies(
        source_gateway=AsyncMock(),
        web_search_service=AsyncMock(),
        web_fetcher=AsyncMock(),
    )
    register_builtin_research_tools(registry, deps)
    names = {t.name for t in registry.list_tools()}
    assert names == {"knowledge.search", "web.search", "web.fetch"}


def test_builtin_provider_assembly_registers_executable_tools():
    """验证内置工具同时注册定义和可执行提供者"""
    from unittest.mock import AsyncMock
    from src.research.providers.builtin import BuiltinResearchDependencies, register_builtin_research_tools
    from src.research.tools.registry import ResearchToolRegistry

    registry = ResearchToolRegistry()
    deps = BuiltinResearchDependencies(
        source_gateway=AsyncMock(),
        web_search_service=AsyncMock(),
        web_fetcher=AsyncMock(),
    )
    register_builtin_research_tools(registry, deps)
    assert {t.name for t in registry.list_tools()} == {"knowledge.search", "web.search", "web.fetch"}
    assert registry.has_provider("knowledge.search")
    assert registry.has_provider("web.search")
    assert registry.has_provider("web.fetch")


def test_mcp_provider_is_disabled_by_default():
    from src.config import Settings
    settings = Settings(DEEPSEEK_API_KEY="test", _env_file=None)
    assert settings.research_mcp_enabled is False


def test_discovered_mcp_tool_requires_explicit_policy():
    from src.research.providers.mcp import McpResearchProvider, ApprovedDynamicTool, UnapprovedDynamicToolError
    provider = McpResearchProvider({})
    with pytest.raises(UnapprovedDynamicToolError):
        provider.definition_for("unknown.tool")
