"""
研究用量记录
持久化模型和工具调用的 token、成本和耗时，支持按任务汇总
"""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research_execution import ResearchUsage


@dataclass(frozen=True)
class ResearchUsageTotals:
    """研究任务累计用量"""

    total_tokens: int
    estimated_cost_microunits: int
    total_latency_ms: int
    tool_calls: int


class ResearchUsageRecorder:
    """持久化并汇总研究模型与工具用量"""

    async def record(
        self,
        db: AsyncSession,
        *,
        workspace_id: str,
        task_id: str,
        step_id: str | None = None,
        provider: str,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_microunits: int = 0,
        latency_ms: int = 0,
    ) -> ResearchUsage:
        """保存一次用量记录

        参数:
            db: 异步数据库会话
            workspace_id: 工作空间 ID
            task_id: 研究任务 ID
            step_id: 可选步骤 ID
            provider: LLM 提供商或工具名
            model: 模型名
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            estimated_cost_microunits: 预估成本微单位
            latency_ms: 调用耗时

        返回:
            ResearchUsage: 已持久化用量记录
        """
        usage = ResearchUsage(
            workspace_id=workspace_id,
            task_id=task_id,
            step_id=step_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_microunits=estimated_cost_microunits,
            latency_ms=latency_ms,
        )
        db.add(usage)
        await db.flush()
        return usage

    async def totals(
        self, db: AsyncSession, workspace_id: str, task_id: str
    ) -> ResearchUsageTotals:
        """查询任务的累计用量

        参数:
            db: 异步数据库会话
            workspace_id: 工作空间 ID
            task_id: 研究任务 ID

        返回:
            ResearchUsageTotals: 累计统计
        """
        result = await db.execute(
            select(
                func.coalesce(func.sum(ResearchUsage.input_tokens + ResearchUsage.output_tokens), 0),
                func.coalesce(func.sum(ResearchUsage.estimated_cost_microunits), 0),
                func.coalesce(func.sum(ResearchUsage.latency_ms), 0),
                func.count(ResearchUsage.id),
            ).where(
                ResearchUsage.workspace_id == workspace_id,
                ResearchUsage.task_id == task_id,
            )
        )
        tokens, cost, latency, count = result.one()
        return ResearchUsageTotals(
            total_tokens=int(tokens),
            estimated_cost_microunits=int(cost),
            total_latency_ms=int(latency),
            tool_calls=int(count),
        )
