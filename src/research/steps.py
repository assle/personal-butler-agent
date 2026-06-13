"""
研究步骤认领与租约管理
使用 PostgreSQL 行锁实现并发安全的步骤认领和过期租约恢复
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research_execution import ResearchStep, ResearchStepDependency
from src.research.schemas import ResearchStepStatus

logger = logging.getLogger(__name__)


def _dialect_supports_lock(db: AsyncSession) -> bool:
    """判断当前数据库是否支持 FOR UPDATE 行锁

    SQLite 不支持 FOR UPDATE，仅 PostgreSQL 等支持。
    """
    try:
        bind = db.get_bind()
        return bind.dialect.name != "sqlite"
    except Exception:
        return False


class StepNotReadyError(RuntimeError):
    """步骤不可认领"""


class ResearchStepService:
    """认领、调度和恢复研究步骤"""

    def __init__(self, lease_seconds: int = 120):
        """初始化步骤服务

        参数:
            lease_seconds: 步骤租约秒数
        """
        self._lease_seconds = lease_seconds

    async def claim_next(
        self, db: AsyncSession, *, owner: str, limit: int = 1, task_id: str | None = None,
    ) -> list[ResearchStep]:
        """认领最多 limit 个就绪步骤

        使用 SELECT ... FOR UPDATE SKIP LOCKED 实现并发安全认领。
        可选按 task_id 过滤，用于定向派发某任务的就绪步骤。

        参数:
            db: 异步数据库会话
            owner: Worker 标识
            limit: 最多认领数
            task_id: 可选任务 ID 过滤

        返回:
            list[ResearchStep]: 已认领并为 running 的步骤
        """
        now = datetime.now(timezone.utc)
        conditions = [
            ResearchStep.status == ResearchStepStatus.READY.value,
            ResearchStep.available_at <= now,
        ]
        if task_id is not None:
            conditions.append(ResearchStep.task_id == task_id)
        query = (
            select(ResearchStep)
            .where(*conditions)
            .order_by(ResearchStep.available_at, ResearchStep.id)
            .limit(limit)
        )
        if _dialect_supports_lock(db):
            query = query.with_for_update(skip_locked=True)
        result = await db.execute(query)
        steps = result.scalars().all()

        claimed: list[ResearchStep] = []
        for step in steps:
            step.status = ResearchStepStatus.RUNNING.value
            step.owner = owner
            step.attempt_count += 1
            step.lease_expires_at = now + timedelta(seconds=self._lease_seconds)
            claimed.append(step)

        if claimed:
            await db.flush()
            logger.info(
                "Step: claimed %d step(s) for owner=%s",
                len(claimed), owner,
            )
        return claimed

    async def release_claim(self, db: AsyncSession, step_id: str, *, owner: str) -> bool:
        """队列发送失败时释放指定所有者的步骤租约

        将 running 状态的步骤恢复为 ready，仅当 owner 匹配时生效。

        参数:
            db: 异步数据库会话
            step_id: 步骤 ID
            owner: 租约所有者

        返回:
            bool: 是否成功释放
        """
        from sqlalchemy import update as _update
        now = datetime.now(timezone.utc)
        result = await db.execute(
            _update(ResearchStep).where(
                ResearchStep.id == step_id,
                ResearchStep.status == ResearchStepStatus.RUNNING.value,
                ResearchStep.owner == owner,
            ).values(
                status=ResearchStepStatus.READY.value,
                owner=None,
                lease_expires_at=None,
                updated_at=now,
            )
        )
        await db.flush()
        return result.rowcount == 1

    async def complete_step(
        self,
        db: AsyncSession,
        step_id: str,
        *,
        result_ref: str | None = None,
        error: str | None = None,
    ) -> ResearchStep:
        """完成步骤并解除后续依赖阻塞

        参数:
            db: 异步数据库会话
            step_id: 步骤 ID
            result_ref: 成功时的结果引用
            error: 失败时的错误信息

        返回:
            ResearchStep: 更新后的步骤
        """
        step = await db.get(ResearchStep, step_id)
        if step is None:
            raise ValueError(f"步骤 {step_id} 不存在")

        if error:
            step.status = ResearchStepStatus.FAILED.value
            step.error = error
            # 终止所有依赖此步骤的步骤
            await self._cancel_dependents(db, step_id)
        else:
            step.status = ResearchStepStatus.COMPLETED.value
            step.result_ref = result_ref

        step.lease_expires_at = None
        now = datetime.now(timezone.utc)
        step.updated_at = now
        await db.flush()

        if not error:
            # 解除阻塞的依赖步骤
            await self._unblock_dependents(db, step_id)

        return step

    async def recover_expired_leases(
        self, db: AsyncSession, *, limit: int = 100
    ) -> list[str]:
        """恢复过期租约的步骤

        参数:
            db: 异步数据库会话
            limit: 最大恢复数

        返回:
            list[str]: 已恢复的步骤 ID 列表
        """
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(ResearchStep).where(
                ResearchStep.status == ResearchStepStatus.RUNNING.value,
                ResearchStep.lease_expires_at < now,
            ).limit(limit)
        )
        expired = result.scalars().all()

        recovered_ids: list[str] = []
        for step in expired:
            step.status = ResearchStepStatus.READY.value
            step.owner = None
            step.lease_expires_at = None
            recovered_ids.append(step.id)

        if recovered_ids:
            await db.flush()
            logger.info("Step: recovered %d expired leases", len(recovered_ids))
        return recovered_ids

    async def mark_root_steps_ready(
        self, db: AsyncSession, task_id: str
    ) -> int:
        """将任务的无依赖步骤标记为 ready

        参数:
            db: 异步数据库会话
            task_id: 研究任务 ID

        返回:
            int: 标记为 ready 的步骤数
        """
        # 查找没有依赖的所有步骤
        subquery = (
            select(ResearchStepDependency.step_id)
        )
        all_steps = await db.execute(
            select(ResearchStep.id).where(
                ResearchStep.task_id == task_id,
                ResearchStep.status == ResearchStepStatus.PENDING.value,
            )
        )
        pending_ids = {row[0] for row in all_steps.all()}
        dependent_ids = {
            row[0] for row in (await db.execute(subquery)).all()
        }
        root_ids = pending_ids - dependent_ids

        if root_ids:
            now = datetime.now(timezone.utc)
            await db.execute(
                update(ResearchStep)
                .where(ResearchStep.id.in_(root_ids))
                .values(
                    status=ResearchStepStatus.READY.value,
                    available_at=now,
                    updated_at=now,
                )
            )
            await db.flush()
            logger.info("Step: marked %d root step(s) ready for task %s",
                        len(root_ids), task_id)
        return len(root_ids)

    async def _unblock_dependents(
        self, db: AsyncSession, completed_step_id: str
    ) -> None:
        """解除依赖 completed_step_id 的阻塞步骤（批量查询避免 N+1）

        参数:
            db: 异步数据库会话
            completed_step_id: 已完成的步骤 ID
        """
        # 查找依赖此步骤的所有步骤
        dep_result = await db.execute(
            select(ResearchStepDependency.step_id).where(
                ResearchStepDependency.depends_on_step_id == completed_step_id,
            )
        )
        dependent_step_ids = {row[0] for row in dep_result.all()}
        if not dependent_step_ids:
            return

        now = datetime.now(timezone.utc)
        for dep_step_id in dependent_step_ids:
            # 一次查询检查该步骤的所有依赖是否都已完成
            incomplete = await db.execute(
                select(ResearchStep).where(
                    ResearchStep.id.in_(
                        select(ResearchStepDependency.depends_on_step_id).where(
                            ResearchStepDependency.step_id == dep_step_id,
                        )
                    ),
                    ResearchStep.status.notin_([
                        ResearchStepStatus.COMPLETED.value,
                    ]),
                )
            )
            if incomplete.first() is None:
                # 所有依赖已完成，解除阻塞
                await db.execute(
                    update(ResearchStep)
                    .where(ResearchStep.id == dep_step_id)
                    .values(
                        status=ResearchStepStatus.READY.value,
                        available_at=now,
                        updated_at=now,
                    )
                )

    async def _cancel_dependents(
        self, db: AsyncSession, failed_step_id: str
    ) -> None:
        """取消依赖失败步骤的所有后续步骤（递归传播）"""
        dep_result = await db.execute(
            select(ResearchStepDependency.step_id).where(
                ResearchStepDependency.depends_on_step_id == failed_step_id,
            )
        )
        for (step_id,) in dep_result.all():
            step = await db.get(ResearchStep, step_id)
            if step and step.status not in (
                ResearchStepStatus.COMPLETED.value,
                ResearchStepStatus.FAILED.value,
                ResearchStepStatus.CANCELLED.value,
            ):
                step.status = ResearchStepStatus.CANCELLED.value
                step.error = f"前置步骤 {failed_step_id} 执行失败"
                step.updated_at = datetime.now(timezone.utc)
                # 递归取消依赖此步骤的后续步骤
                await self._cancel_dependents(db, step_id)
