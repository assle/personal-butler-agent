"""研究计划持久化服务"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchTask
from src.models.research_execution import (
    ResearchPlan,
    ResearchStep,
    ResearchStepDependency,
)
from src.research.planning.schemas import PlanDraft
from src.research.schemas import ResearchStepStatus

logger = logging.getLogger(__name__)


class PlanService:
    """原子持久化版本化研究计划"""

    async def persist(
        self,
        db: AsyncSession,
        *,
        workspace_id: str,
        task_id: str,
        draft: PlanDraft,
    ) -> ResearchPlan:
        """在同一事务中创建计划、步骤和依赖

        参数:
            db: 异步数据库会话
            workspace_id: 工作空间 ID
            task_id: 研究任务 ID
            draft: 已验证的 PlanDraft

        返回:
            ResearchPlan: 已持久化计划
        """
        # 计算版本号
        existing = await db.execute(
            select(ResearchPlan)
            .where(
                ResearchPlan.task_id == task_id,
                ResearchPlan.workspace_id == workspace_id,
            )
        )
        current_version = len(existing.scalars().all())
        version = current_version + 1

        now = datetime.now(timezone.utc)

        # 插入计划
        plan = ResearchPlan(
            workspace_id=workspace_id,
            task_id=task_id,
            version=version,
            objective=draft.objective,
            completion_criteria=draft.completion_criteria,
            estimated_cost_microunits=draft.estimated_cost_microunits,
            estimated_tokens=draft.estimated_tokens,
            raw_plan=draft.model_dump(),
            created_at=now,
        )
        db.add(plan)
        await db.flush()

        # 插入步骤（使用确定性 ID: {task_id}:{version}:{key}）
        step_key_to_id: dict[str, str] = {}
        for step_draft in draft.steps:
            step_id = f"{task_id}:{version}:{step_draft.key}"
            step = ResearchStep(
                id=step_id,
                workspace_id=workspace_id,
                task_id=task_id,
                plan_id=plan.id,
                kind=step_draft.kind,
                tool_name=step_draft.tool_name,
                input_payload=step_draft.input_payload,
                status=ResearchStepStatus.PENDING.value,
                max_attempts=step_draft.max_attempts,
                idempotency_key=f"{task_id}:{version}:{step_draft.key}",
                created_at=now,
            )
            db.add(step)
            step_key_to_id[step_draft.key] = step_id
        await db.flush()

        # 插入依赖
        for step_draft in draft.steps:
            for dep_key in step_draft.depends_on:
                db.add(ResearchStepDependency(
                    step_id=step_key_to_id[step_draft.key],
                    depends_on_step_id=step_key_to_id[dep_key],
                ))

        await db.flush()
        logger.info("Plan: persisted plan_id=%d task_id=%s version=%d steps=%d",
                     plan.id, task_id, version, len(draft.steps))
        return plan
