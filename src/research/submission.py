"""
私聊研究任务提交与查询门面
把 PrivateButlerAgent 与持久化、队列派发隔离。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.governance.hooks import CriticalHookError, HookEvent
from src.governance.workspaces import (
    AmbiguousWorkspaceError,
    WorkspaceAccessDeniedError,
    WorkspaceContext,
)
from src.models.research import ResearchReport
from src.research.service import ResearchTaskService, UserResearchBusyError


class ResearchSubmissionService:
    """私聊研究提交和状态查询服务"""

    def __init__(
        self,
        task_service: ResearchTaskService,
        dispatcher,
        *,
        workspace_service=None,
        hook_bus=None,
        approval_service=None,
        step_dispatcher=None,
    ):
        """注入任务服务、队列派发器、工作空间服务、Hook 总线和审批服务"""
        self._tasks = task_service
        self._dispatcher = dispatcher
        self._workspace_service = workspace_service
        self._hook_bus = hook_bus
        self._approval_service = approval_service
        self._step_dispatcher = step_dispatcher

    async def submit(
        self,
        db: AsyncSession,
        *,
        source_msgid: str,
        requester_open_userid: str,
        question: str,
    ) -> str:
        """创建并派发任务；重复回调返回同一任务 ID；
        通过 WorkspaceService 解析成员身份，发射 BEFORE_RESEARCH Hook。
        """
        if not source_msgid:
            return "研究任务缺少消息标识，暂时无法可靠创建。"

        # 解析工作空间上下文
        if self._workspace_service is not None:
            try:
                ws_ctx = await self._workspace_service.resolve_member(
                    db, requester_open_userid
                )
            except WorkspaceAccessDeniedError:
                return "你没有访问任何工作空间的权限，无法创建研究任务。"
            except AmbiguousWorkspaceError:
                return "你属于多个工作空间，请指定工作空间 ID 后再试。"

            # 发射 BEFORE_RESEARCH Hook
            if self._hook_bus is not None:
                try:
                    await self._hook_bus.emit(
                        HookEvent.BEFORE_RESEARCH,
                        {
                            "open_userid": requester_open_userid,
                            "question": question,
                        },
                    )
                except CriticalHookError:
                    return "研究任务未通过审批检查，无法创建。"
        else:
            # 向后兼容：无工作空间服务时使用配置默认值
            from src.config import settings

            # 向后兼容路径：member_id=0 为占位值，
            # 表示未通过 WorkspaceService 解析，不作为真实 member 引用
            ws_ctx = WorkspaceContext(
                workspace_id=settings.default_workspace_id,
                member_id=0,
                open_userid=requester_open_userid,
                role="member",
                research_approved_once=True,
            )

        try:
            task, created = await self._tasks.create_task(
                db,
                workspace=ws_ctx,
                source_msgid=source_msgid,
                question=question,
            )
        except UserResearchBusyError as exc:
            return f"你已有运行中的研究任务 {exc}，请完成后再提交新任务。"
        if created or task.enqueued_at is None:
            # 必须先提交数据库，再发布 task_id，避免 Worker 抢先读取不到任务。
            await db.commit()
            try:
                await self._dispatcher.enqueue_planning(task.id)
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
            f"已创建研究任务 {task.id}。\n"
            "系统将规划检索范围；首次使用或高成本计划可能需要你批准。\n"
            f"查询状态: 查看研究任务 {task.id}"
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

    async def approve(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        requester_open_userid: str,
    ) -> str:
        """批准研究任务"""
        if self._workspace_service is None:
            return "审批功能需要工作空间服务支持。"
        try:
            ws_ctx = await self._workspace_service.resolve_member(db, requester_open_userid)
        except Exception:
            return "无法解析工作空间身份，审批失败。"
        try:
            await self._approval_service.approve(db, workspace=ws_ctx, task_id=task_id)
            await db.commit()
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"审批失败：{e}"
        if self._step_dispatcher is not None:
            try:
                await self._step_dispatcher.dispatch_ready(task_id)
            except Exception as exc:
                return f"已批准研究任务 {task_id}，但步骤派发失败：{exc}"
        return f"已批准研究任务 {task_id}，任务开始执行。"

    async def reject(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        requester_open_userid: str,
        reason: str = "",
    ) -> str:
        """拒绝研究任务"""
        if self._workspace_service is None:
            return "审批功能需要工作空间服务支持。"
        try:
            ws_ctx = await self._workspace_service.resolve_member(db, requester_open_userid)
        except Exception:
            return "无法解析工作空间身份，审批失败。"
        try:
            await self._approval_service.reject(
                db, workspace=ws_ctx, task_id=task_id, reason=reason,
            )
            await db.commit()
            msg = f"已拒绝研究任务 {task_id}"
            if reason:
                msg += f"，原因：{reason}"
            return msg
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"拒绝操作失败：{e}"
