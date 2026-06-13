"""研究工具提供者协议"""
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from src.research.tools.schemas import ToolExecutionContext, ToolExecutionResult


class ResearchToolProvider(Protocol):
    """研究工具提供者接口"""

    async def execute(
        self,
        db: AsyncSession,
        context: ToolExecutionContext,
        arguments: dict,
    ) -> ToolExecutionResult:
        """使用当前事务执行工具并返回结构化结果"""
        ...
