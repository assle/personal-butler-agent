"""研究质量修复协调"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.research.review.service import QualityDecision

logger = logging.getLogger(__name__)


@dataclass
class QualityRepairResult:
    """修复操作结果"""
    action: str  # "retrieve", "weaken", "fail"
    new_step_ids: list[str] = field(default_factory=list)
    weakened_claim_keys: list[str] = field(default_factory=list)
    failed: bool = False


class QualityRepairCoordinator:
    """协调引用失败后的有限修复"""

    def __init__(
        self,
        *,
        task_service,
        plan_service,
        max_repair_rounds: int = 1,
    ):
        self._tasks = task_service
        self._plan_service = plan_service
        self._max_rounds = max_repair_rounds

    async def handle(
        self, db: AsyncSession, task_id: str, decision: QualityDecision
    ) -> QualityRepairResult:
        """处理质量门失败"""
        task = await self._tasks.get_task(db, task_id)

        # 检查剩余修复轮次
        if task.current_round >= self._max_rounds:
            logger.info("Repair: exceeded max rounds for task %s", task_id)
            return QualityRepairResult(
                action="fail",
                failed=True,
                weakened_claim_keys=list(decision.unsupported_claim_keys),
            )

        # 追加定向检索步骤
        if decision.follow_up_queries:
            from src.research.planning.schemas import PlanDraft, StepDraft
            repair_steps = []
            for i, query in enumerate(decision.follow_up_queries[:3]):
                repair_steps.append(StepDraft(
                    key=f"repair_{i + 1}",
                    kind="knowledge_retrieval",
                    tool_name="knowledge.search",
                    input_payload={"query": query},
                ))
            if repair_steps:
                draft = PlanDraft(
                    objective=f"Repair {task_id}",
                    completion_criteria=["fix unsupported claims"],
                    estimated_tokens=500, estimated_cost_microunits=1000,
                    steps=repair_steps,
                )
                plan = await self._plan_service.persist(
                    db, workspace_id=task.workspace_id,
                    task_id=task_id, draft=draft,
                )
                task.current_round += 1
                return QualityRepairResult(
                    action="retrieve",
                    new_step_ids=[f"{task_id}:{plan.version}:{s.key}" for s in repair_steps],
                )

        # 无补检查询，弱化声明
        return QualityRepairResult(
            action="weaken",
            weakened_claim_keys=list(decision.unsupported_claim_keys),
        )
