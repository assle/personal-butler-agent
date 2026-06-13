"""
研究计划审批服务
管理 first-use 和 high-cost 审批的创建、批准和拒绝
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.governance.workspaces import WorkspaceContext
from src.models.research import ResearchTask
from src.models.research_execution import ResearchApproval, ResearchPlan
from src.models.workspace import WorkspaceMember
from src.research.schemas import ResearchTaskStatus
from src.research.steps import ResearchStepService

logger = logging.getLogger(__name__)


class ApprovalPolicy:
    """判定计划是否需要审批"""

    def __init__(self, high_cost_microunits: int = 250_000):
        """初始化审批策略

        参数:
            high_cost_microunits: 高成本审批阈值（微单位）
        """
        self._high_cost = high_cost_microunits

    def evaluate(
        self,
        *,
        first_use: bool,
        estimated_cost: int,
    ) -> bool:
        """返回是否需要审批

        参数:
            first_use: 是否首次使用研究功能
            estimated_cost: 预估成本微单位

        返回:
            bool: True 表示需要审批
        """
        return first_use or estimated_cost > self._high_cost


class ApprovalService:
    """处理研究计划审批的创建和状态转换"""

    def __init__(
        self,
        policy: ApprovalPolicy,
        step_service: ResearchStepService,
    ):
        """初始化审批服务

        参数:
            policy: 审批策略
            step_service: 步骤服务（用于激活步骤）
        """
        self._policy = policy
        self._steps = step_service

    async def request_approval(
        self,
        db: AsyncSession,
        *,
        task: ResearchTask,
        plan: ResearchPlan,
        workspace: WorkspaceContext,
    ) -> ResearchApproval | None:
        """如果策略要求，创建审批记录并将任务转为 awaiting_approval

        参数:
            db: 异步数据库会话
            task: 研究任务
            plan: 已持久化计划
            workspace: 工作空间上下文

        返回:
            ResearchApproval | None: 创建的审批记录，无需审批时返回 None
        """
        needs_approval = self._policy.evaluate(
            first_use=not workspace.research_approved_once,
            estimated_cost=plan.estimated_cost_microunits,
        )
        if not needs_approval:
            return None

        approval = ResearchApproval(
            workspace_id=workspace.workspace_id,
            task_id=task.id,
            plan_id=plan.id,
            policy_id=(
                "research.first_use" if not workspace.research_approved_once
                else "cost.high_approval"
            ),
            status="pending",
            decided_by="system",  # 系统自动创建
            decided_at=datetime.now(timezone.utc),
        )
        db.add(approval)
        task.status = ResearchTaskStatus.AWAITING_APPROVAL.value
        task.updated_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info(
            "Approval: created %s for task %s",
            approval.policy_id, task.id,
        )
        return approval

    async def approve(
        self,
        db: AsyncSession,
        *,
        workspace: WorkspaceContext,
        task_id: str,
        reason: str = "",
    ) -> ResearchApproval:
        """批准研究计划

        参数:
            db: 异步数据库会话
            workspace: 已验证工作空间上下文
            task_id: 研究任务 ID
            reason: 可选审批备注

        返回:
            ResearchApproval: 已更新审批记录
        """
        from sqlalchemy import select as _select

        approval_result = await db.execute(
            _select(ResearchApproval).where(
                ResearchApproval.task_id == task_id,
                ResearchApproval.workspace_id == workspace.workspace_id,
                ResearchApproval.status == "pending",
            )
        )
        approval = approval_result.scalar_one_or_none()
        if approval is None:
            raise ValueError(f"任务 {task_id} 没有待审批的记录")

        approval.status = "approved"
        approval.decided_by = workspace.open_userid
        approval.reason = reason
        approval.decided_at = datetime.now(timezone.utc)

        # 标记成员已审批过一次研究
        member_result = await db.execute(
            _select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.workspace_id,
                WorkspaceMember.open_userid == workspace.open_userid,
            )
        )
        member = member_result.scalar_one_or_none()
        if member is not None:
            member.research_approved_once = True

        # 转换任务状态
        task = await db.get(ResearchTask, task_id)
        task.status = ResearchTaskStatus.RUNNING.value
        task.updated_at = datetime.now(timezone.utc)

        await db.flush()

        # 激活根步骤
        await self._steps.mark_root_steps_ready(db, task_id)
        await db.flush()

        logger.info("Approval: approved task %s by %s", task_id, workspace.open_userid)
        return approval

    async def reject(
        self,
        db: AsyncSession,
        *,
        workspace: WorkspaceContext,
        task_id: str,
        reason: str = "",
    ) -> ResearchApproval:
        """拒绝研究计划

        参数:
            db: 异步数据库会话
            workspace: 已验证工作空间上下文
            task_id: 研究任务 ID
            reason: 拒绝原因

        返回:
            ResearchApproval: 已更新审批记录
        """
        from sqlalchemy import select as _select, update

        approval_result = await db.execute(
            _select(ResearchApproval).where(
                ResearchApproval.task_id == task_id,
                ResearchApproval.workspace_id == workspace.workspace_id,
                ResearchApproval.status == "pending",
            )
        )
        approval = approval_result.scalar_one_or_none()
        if approval is None:
            raise ValueError(f"任务 {task_id} 没有待审批的记录")

        approval.status = "rejected"
        approval.decided_by = workspace.open_userid
        approval.reason = reason
        approval.decided_at = datetime.now(timezone.utc)

        # 取消任务和所有步骤
        task = await db.get(ResearchTask, task_id)
        task.status = ResearchTaskStatus.CANCELLED.value
        task.error = f"用户 {workspace.open_userid} 拒绝了研究计划"
        task.updated_at = datetime.now(timezone.utc)

        from src.models.research_execution import ResearchStep
        from src.research.schemas import ResearchStepStatus
        await db.execute(
            update(ResearchStep)
            .where(ResearchStep.task_id == task_id)
            .where(ResearchStep.status.notin_([
                ResearchStepStatus.COMPLETED.value,
                ResearchStepStatus.FAILED.value,
                ResearchStepStatus.CANCELLED.value,
            ]))
            .values(status=ResearchStepStatus.CANCELLED.value)
        )

        await db.flush()
        logger.info("Approval: rejected task %s by %s", task_id, workspace.open_userid)
        return approval
