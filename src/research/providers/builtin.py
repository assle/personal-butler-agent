"""内置研究工具注册"""
from dataclasses import dataclass

from src.research.tools.registry import ResearchToolRegistry
from src.research.tools.schemas import ResearchToolDefinition


@dataclass(frozen=True)
class BuiltinResearchDependencies:
    source_gateway: object
    web_search_service: object
    web_fetcher: object


def register_builtin_research_tools(
    registry: ResearchToolRegistry,
    deps: BuiltinResearchDependencies,
) -> None:
    """注册内置研究工具定义及其可执行提供者

    参数:
        registry: ResearchToolRegistry 实例
        deps: 内置工具依赖

    返回:
        None
    """
    from src.research.specialists.knowledge import KnowledgeResearcher
    from src.research.specialists.web import WebResearcher
    from src.research.specialists.fetch import WebFetchResearcher

    registry.register(
        ResearchToolDefinition(
            name="knowledge.search", description="Search authorized internal knowledge",
            risk_level="read", data_scope="workspace", cost_class="low",
            timeout_seconds=30, max_attempts=2,
            provider_name="builtin.knowledge", provider_version="1",
        ),
        provider=KnowledgeResearcher(deps.source_gateway),
    )
    registry.register(
        ResearchToolDefinition(
            name="web.search", description="Search public web",
            risk_level="read", data_scope="public_web", cost_class="medium",
            timeout_seconds=30, max_attempts=3,
            provider_name="builtin.web_search", provider_version="1",
        ),
        provider=WebResearcher(deps.web_search_service),
    )
    registry.register(
        ResearchToolDefinition(
            name="web.fetch", description="Fetch validated public page content",
            risk_level="read", data_scope="public_web", cost_class="medium",
            timeout_seconds=15, max_attempts=2,
            provider_name="builtin.web_fetch", provider_version="1",
        ),
        provider=WebFetchResearcher(deps.web_fetcher),
    )
