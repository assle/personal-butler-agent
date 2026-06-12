"""
研究任务生命周期服务
负责创建、幂等、单用户并发限制、状态转换、报告持久化和权限化查询。
"""
from datetime import datetime, timezone
from secrets import token_hex

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchDelivery, ResearchReport, ResearchTask
from src.research.schemas import (
    ACTIVE_RESEARCH_STATUSES,
    ResearchReportSnapshot,
    ResearchTaskStatus,
)


class UserResearchBusyError(RuntimeError):
    """当前用户已有运行中的研究任务"""


class ResearchTaskNotFoundError(RuntimeError):
    """研究任务不存在"""


def _new_task_id() -> str:
    """生成用户可读、数据库稳定的研究任务 ID"""
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"R{date}-{token_hex(4).upper()}"


class ResearchTaskService:
    """研究任务持久化服务"""

    def __init__(self, max_rounds: int, timeout_seconds: int):
        """初始化默认预算"""
        self._max_rounds = max_rounds
        self._timeout_seconds = timeout_seconds

    async def create_task(
        self,
        db: AsyncSession,
        *,
        source_msgid: str,
        requester_open_userid: str,
        question: str,
    ) -> tuple[ResearchTask, bool]:
        """按回调 msgid 幂等创建任务，并限制每用户一个活动任务"""
        existing = (
            await db.execute(
                select(ResearchTask).where(ResearchTask.source_msgid == source_msgid)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

        active = (
            await db.execute(
                select(ResearchTask).where(
                    ResearchTask.requester_open_userid == requester_open_userid,
                    ResearchTask.status.in_(ACTIVE_RESEARCH_STATUSES),
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            raise UserResearchBusyError(active.id)

        task = ResearchTask(
            id=_new_task_id(),
            source_msgid=source_msgid,
            requester_open_userid=requester_open_userid,
            question=question.strip(),
            research_type="foundation",
            status=ResearchTaskStatus.QUEUED.value,
            access_scope={
                "public": True,
                "user_id": requester_open_userid,
                "group_ids": [],
                "web": True,
            },
            max_rounds=self._max_rounds,
            timeout_seconds=self._timeout_seconds,
        )
        db.add(task)
        await db.flush()
        db.add(ResearchDelivery(task_id=task.id, status="pending"))
        await db.flush()
        return task, True

    async def get_task(self, db: AsyncSession, task_id: str) -> ResearchTask:
        """按 ID 获取任务，不存在时抛出明确异常"""
        task = await db.get(ResearchTask, task_id)
        if task is None:
            raise ResearchTaskNotFoundError(task_id)
        return task

    async def get_user_task(
        self, db: AsyncSession, task_id: str, requester_open_userid: str
    ) -> ResearchTask | None:
        """只返回属于当前用户的任务"""
        return (
            await db.execute(
                select(ResearchTask).where(
                    ResearchTask.id == task_id,
                    ResearchTask.requester_open_userid == requester_open_userid,
                )
            )
        ).scalar_one_or_none()

    async def mark_running(self, db: AsyncSession, task_id: str) -> ResearchTask:
        """将 queued 任务标记为 running；已完成任务保持幂等"""
        task = await self.get_task(db, task_id)
        if task.status == ResearchTaskStatus.COMPLETED.value:
            return task
        task.status = ResearchTaskStatus.RUNNING.value
        task.started_at = task.started_at or datetime.now(timezone.utc)
        task.error = None
        await db.flush()
        return task

    async def mark_enqueued(self, db: AsyncSession, task_id: str) -> ResearchTask:
        """记录任务已成功提交到 Redis Stream"""
        task = await self.get_task(db, task_id)
        task.enqueued_at = task.enqueued_at or datetime.now(timezone.utc)
        await db.flush()
        return task

    async def complete_with_report(
        self,
        db: AsyncSession,
        task_id: str,
        *,
        summary: str,
        body: str,
        quality_status: str,
    ) -> ResearchReport:
        """创建首版报告并完成任务；重复执行返回已存在报告"""
        existing = (
            await db.execute(
                select(ResearchReport).where(
                    ResearchReport.task_id == task_id,
                    ResearchReport.version == 1,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        task = await self.get_task(db, task_id)
        report = ResearchReport(
            task_id=task_id,
            version=1,
            summary=summary,
            body=body,
            quality_status=quality_status,
        )
        db.add(report)
        task.status = ResearchTaskStatus.COMPLETED.value
        task.quality_status = quality_status
        task.completed_at = datetime.now(timezone.utc)
        task.error = None
        await db.flush()
        return report

    async def mark_failed(
        self, db: AsyncSession, task_id: str, error: str
    ) -> ResearchTask:
        """记录研究执行失败"""
        task = await self.get_task(db, task_id)
        task.status = ResearchTaskStatus.FAILED.value
        task.error = error[:1000]
        task.completed_at = datetime.now(timezone.utc)
        await db.flush()
        return task

    async def mark_timed_out(
        self, db: AsyncSession, task_id: str, error: str
    ) -> ResearchTask:
        """记录研究任务超过硬时间预算"""
        task = await self.get_task(db, task_id)
        task.status = ResearchTaskStatus.TIMED_OUT.value
        task.error = error[:1000]
        task.completed_at = datetime.now(timezone.utc)
        await db.flush()
        return task

    async def get_report_snapshot(
        self, db: AsyncSession, task_id: str
    ) -> ResearchReportSnapshot:
        """加载投递所需任务与首版报告"""
        task = await self.get_task(db, task_id)
        report = (
            await db.execute(
                select(ResearchReport).where(
                    ResearchReport.task_id == task_id,
                    ResearchReport.version == 1,
                )
            )
        ).scalar_one()
        return ResearchReportSnapshot(
            task_id=task.id,
            requester_open_userid=task.requester_open_userid,
            question=task.question,
            summary=report.summary,
            body=report.body,
            quality_status=report.quality_status,
        )
