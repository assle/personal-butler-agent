"""
研究步骤执行器
认领步骤后执行工具调用，持久化证据，解锁后续步骤
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research_execution import ResearchStep
from src.research.evidence import EvidenceInput, ResearchEvidenceService
from src.research.tools.schemas import ToolExecutionContext, ToolExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class StepExecutionResult:
    """步骤执行结果"""
    step_id: str
    success: bool
    result_ref: str | None = None
    error: str | None = None
    evidence_ids: list[int] = field(default_factory=list)
    unblocked_step_ids: list[str] = field(default_factory=list)


class ResearchStepExecutor:
    """执行已认领的研究工具步骤"""

    def __init__(
        self,
        *,
        registry,
        evidence_service: ResearchEvidenceService,
        step_service,
    ):
        self._registry = registry
        self._evidence = evidence_service
        self._steps = step_service

    async def execute(
        self,
        db: AsyncSession,
        step_id: str,
        worker_id: str,
    ) -> StepExecutionResult:
        """执行单个研究步骤

        参数:
            db: 异步数据库会话
            step_id: 已派发步骤 ID
            worker_id: Worker 唯一标识

        返回:
            StepExecutionResult
        """
        step = await db.get(ResearchStep, step_id)
        if step is None:
            return StepExecutionResult(step_id=step_id, success=False, error="步骤不存在")

        # 验证租约所有权
        if step.owner != worker_id:
            return StepExecutionResult(step_id=step_id, success=False, error="步骤不属于当前 Worker")

        context = ToolExecutionContext(
            workspace_id=step.workspace_id,
            user_id="system",
            task_id=step.task_id,
            step_id=step_id,
        )

        # 执行工具
        tool_result = await self._registry.execute(
            context, step.tool_name, step.input_payload,
        )

        if not tool_result.success:
            await self._steps.complete_step(db, step_id, error=tool_result.error)
            logger.warning("Step %s: tool failed — %s", step_id, tool_result.error)
            return StepExecutionResult(
                step_id=step_id, success=False, error=tool_result.error,
            )

        # 持久化证据
        evidence_ids = []
        evidence_list = tool_result.data.get("evidence", [])
        for ev_data in evidence_list:
            try:
                evidence_input = EvidenceInput(**ev_data)
                evidence = await self._evidence.store(db, evidence_input)
                evidence_ids.append(evidence.id)
            except Exception as e:
                logger.warning("Step %s: evidence persist failed — %s", step_id, e)

        result_ref = f"evidence:{','.join(map(str, evidence_ids))}" if evidence_ids else "completed"

        # 完成步骤
        completed_step = await self._steps.complete_step(db, step_id, result_ref=result_ref)

        logger.info(
            "Step %s: done, evidence=%d", step_id, len(evidence_ids),
        )
        return StepExecutionResult(
            step_id=step_id, success=True, result_ref=result_ref,
            evidence_ids=evidence_ids,
        )
