"""MCP 研究工具适配器（默认关闭，预留扩展边界）"""
from dataclasses import dataclass

class UnapprovedDynamicToolError(RuntimeError):
    pass

@dataclass(frozen=True)
class ApprovedDynamicTool:
    name: str
    risk_level: str
    data_scope: str
    cost_class: str

class McpResearchProvider:
    def __init__(self, approved_tools: dict[str, ApprovedDynamicTool]):
        self._approved = approved_tools

    def definition_for(self, tool_name: str) -> ApprovedDynamicTool:
        if tool_name not in self._approved:
            raise UnapprovedDynamicToolError(f"动态工具 {tool_name} 未被授权")
        return self._approved[tool_name]
