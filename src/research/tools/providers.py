"""研究工具提供者协议"""
from typing import Protocol
from src.research.tools.schemas import ToolExecutionContext, ToolExecutionResult


class ResearchToolProvider(Protocol):
    """研究工具提供者接口"""

    async def execute(
        self,
        context: ToolExecutionContext,
        arguments: dict,
    ) -> ToolExecutionResult:
        """执行工具并返回结构化结果"""
        ...
