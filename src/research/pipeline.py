"""
研究管线协调器
使用任务状态转换协调阶段和队列派发，保证幂等
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update as _update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchReport
from src.models.research_execution import ResearchStep
from src.research.schemas import ResearchTaskStatus, ResearchStepStatus
from src.research.service import InvalidResearchTransitionError

logger = logging.getLogger(__name__)


class ResearchPipelineCoordinator:
    """使用任务状态转换协调研究阶段和队列派发"""

    def __init__(self, *, task_service, dispatcher, synthesis_dispatcher, validation_dispatcher, delivery_dispatcher, step_dispatcher):
        """初始化管线协调器

        参数:
            task_service: 任务服务
            dispatcher: 通用队列派发器
            synthesis_dispatcher: 综合任务派发器
            validation_dispatcher: 验证任务派发器
            delivery_dispatcher: 投递任务派发器
            step_dispatcher: 步骤派发器
        """
        self._tasks = task_service
        self._queue = dispatcher
        self._synth = synthesis_dispatcher
        self._validate = validation_dispatcher
        self._deliver = delivery_dispatcher
        self._step = step_dispatcher

    async def queue_synthesis_if_complete(self, db: AsyncSession, task_id: str) -> bool:
        """全部步骤完成时原子进入综合阶段并派发一次

        当任务所有步骤（包括已完成和已取消）均终结时，将任务从 RUNNING
        原子转换到 SYNTHESIZING 并派发综合任务。已处于 SYNTHESIZING 时幂等返回 False。

        参数:
            db: 异步数据库会话
            task_id: 研究任务 ID

        返回:
            bool: 是否成功进入综合阶段
        """
        task = await self._tasks.get_task(db, task_id)
        result = await db.execute(select(ResearchStep).where(ResearchStep.task_id == task_id))
        steps = result.scalars().all()
        all_done = all(
            s.status in (
                ResearchStepStatus.COMPLETED.value,
                ResearchStepStatus.FAILED.value,
                ResearchStepStatus.CANCELLED.value,
            )
            for s in steps
        )
        has_success = any(
            s.status == ResearchStepStatus.COMPLETED.value for s in steps
        )
        if not all_done or not has_success:
            return False
        try:
            await self._tasks.transition(
                db, task_id, task.workspace_id,
                expected={ResearchTaskStatus.RUNNING},
                target=ResearchTaskStatus.SYNTHESIZING,
            )
            await db.commit()
            await self._synth.enqueue_synthesis(task_id)
            return True
        except InvalidResearchTransitionError:
            return False

    async def queue_validation(self, db: AsyncSession, task_id: str) -> bool:
        """报告草稿落库后进入验证阶段并派发一次

        参数:
            db: 异步数据库会话
            task_id: 研究任务 ID

        返回:
            bool: 是否成功进入验证阶段
        """
        task = await self._tasks.get_task(db, task_id)
        try:
            await self._tasks.transition(
                db, task_id, task.workspace_id,
                expected={ResearchTaskStatus.SYNTHESIZING},
                target=ResearchTaskStatus.VALIDATING,
            )
            await db.commit()
            await self._validate.enqueue_validation(task_id)
            return True
        except InvalidResearchTransitionError:
            return False

    async def complete_and_queue_delivery(self, db: AsyncSession, task_id: str) -> bool:
        """报告通过质量门后完成任务并派发投递

        参数:
            db: 异步数据库会话
            task_id: 研究任务 ID

        返回:
            bool: 是否成功完成并投递
        """
        task = await self._tasks.get_task(db, task_id)
        try:
            await self._tasks.transition(
                db, task_id, task.workspace_id,
                expected={ResearchTaskStatus.VALIDATING},
                target=ResearchTaskStatus.COMPLETED,
            )
            from src.models.research import ResearchReport
            from sqlalchemy import update as _update
            await db.execute(
                _update(ResearchReport)
                .where(ResearchReport.task_id == task_id)
                .values(report_status="validated", validated_at=datetime.now(timezone.utc))
            )
            await db.commit()
            await self._deliver.enqueue_delivery(task_id)
            return True
        except InvalidResearchTransitionError:
            return False

    async def repair_and_retry(self, db: AsyncSession, task_id: str, new_step_ids: list[str]) -> bool:
        """修复后返回 running 并派发新步骤

        参数:
            db: 异步数据库会话
            task_id: 研究任务 ID
            new_step_ids: 新创建的修复步骤 ID 列表

        返回:
            bool: 是否成功进入重试状态
        """
        task = await self._tasks.get_task(db, task_id)
        try:
            await self._tasks.transition(
                db, task_id, task.workspace_id,
                expected={ResearchTaskStatus.VALIDATING},
                target=ResearchTaskStatus.RUNNING,
            )
            await db.commit()
            for sid in new_step_ids:
                await self._step.enqueue_step(sid)
            return True
        except InvalidResearchTransitionError:
            return False
