"""
私聊研究任务提交与查询门面
把 PrivateButlerAgent 与持久化、队列派发隔离。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchReport
from src.research.service import ResearchTaskService, UserResearchBusyError


class ResearchSubmissionService:
    """私聊研究提交和状态查询服务"""

    def __init__(self, task_service: ResearchTaskService, dispatcher):
        """注入任务服务和队列派发器"""
        self._tasks = task_service
        self._dispatcher = dispatcher

    async def submit(
        self,
        db: AsyncSession,
        *,
        source_msgid: str,
        requester_open_userid: str,
        question: str,
    ) -> str:
        """创建并派发任务；重复回调返回同一任务 ID"""
        if not source_msgid:
            return "研究任务缺少消息标识，暂时无法可靠创建。"
        try:
            task, created = await self._tasks.create_task(
                db,
                source_msgid=source_msgid,
                requester_open_userid=requester_open_userid,
                question=question,
            )
        except UserResearchBusyError as exc:
            return f"你已有运行中的研究任务 {exc}，请完成后再提交新任务。"
        if created or task.enqueued_at is None:
            # 必须先提交数据库，再发布 task_id，避免 Worker 抢先读取不到任务。
            await db.commit()
            try:
                await self._dispatcher.enqueue_research(task.id)
                await self._tasks.mark_enqueued(db, task.id)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                await self._tasks.mark_failed(
                    db, task.id, f"queue dispatch failed: {exc}"
                )
                await db.commit()
                return "研究任务入队失败，请稍后重新提交。"
        return (
            f"已创建研究任务 {task.id}。完成后会通过企微自建应用主动私聊通知。\n"
            "当前 Phase 1 输出为未审核初稿，不含多来源检索和逐项引用。"
        )

    async def status(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        requester_open_userid: str,
    ) -> str:
        """查询当前用户自己的任务状态和已完成初稿"""
        task = await self._tasks.get_user_task(
            db, task_id.upper(), requester_open_userid
        )
        if task is None:
            return "没有找到属于你的该研究任务。"
        if task.status != "completed":
            detail = f"\n失败原因：{task.error}" if task.error else ""
            return f"研究任务 {task.id} 当前状态：{task.status}{detail}"
        report = (
            await db.execute(
                select(ResearchReport).where(
                    ResearchReport.task_id == task.id,
                    ResearchReport.version == 1,
                )
            )
        ).scalar_one()
        return (
            f"研究任务 {task.id} 已完成。\n"
            f"质量状态：{report.quality_status}\n\n{report.body}"
        )
