"""Provider 注册测试"""
import pytest
from src.research.tools.registry import ResearchToolRegistry
from src.research.providers.builtin import BuiltinResearchDependencies, register_builtin_research_tools


def test_builtin_provider_registers_expected_tools():
    registry = ResearchToolRegistry()
    register_builtin_research_tools(registry, BuiltinResearchDependencies())
    names = {t.name for t in registry.list_tools()}
    assert names == {"knowledge.search", "web.search", "web.fetch"}


def test_mcp_provider_is_disabled_by_default():
    from src.config import Settings
    settings = Settings(DEEPSEEK_API_KEY="test", _env_file=None)
    assert settings.research_mcp_enabled is False


def test_discovered_mcp_tool_requires_explicit_policy():
    from src.research.providers.mcp import McpResearchProvider, ApprovedDynamicTool, UnapprovedDynamicToolError
    provider = McpResearchProvider({})
    with pytest.raises(UnapprovedDynamicToolError):
        provider.definition_for("unknown.tool")
