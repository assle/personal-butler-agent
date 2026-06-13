"""内置研究工具注册"""
from dataclasses import dataclass
from src.research.tools.registry import ResearchToolRegistry
from src.research.tools.schemas import ResearchToolDefinition

@dataclass(frozen=True)
class BuiltinResearchDependencies:
    source_gateway: object = None
    web_fetcher: object = None
    evidence_service: object = None

def register_builtin_research_tools(registry: ResearchToolRegistry, deps: BuiltinResearchDependencies) -> None:
    registry.register(ResearchToolDefinition(
        name="knowledge.search", description="Search authorized internal knowledge",
        risk_level="read", data_scope="workspace", cost_class="low",
        timeout_seconds=30, max_attempts=2, provider_name="builtin.knowledge", provider_version="1",
    ))
    registry.register(ResearchToolDefinition(
        name="web.search", description="Search public web",
        risk_level="read", data_scope="public_web", cost_class="medium",
        timeout_seconds=30, max_attempts=3, provider_name="builtin.web_search", provider_version="1",
    ))
    registry.register(ResearchToolDefinition(
        name="web.fetch", description="Fetch full page content from validated URLs",
        risk_level="read", data_scope="public_web", cost_class="medium",
        timeout_seconds=15, max_attempts=2, provider_name="builtin.web_fetch", provider_version="1",
    ))
