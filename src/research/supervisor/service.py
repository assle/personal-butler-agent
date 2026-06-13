"""研究 Supervisor 服务"""
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.research.planning.schemas import PlanDraft
from src.research.budgets import BudgetLimits
from src.research.planning.validator import PlanValidator
from src.research.supervisor.planner import PlanningResult, TaskSnapshot
from src.research.supervisor.prompts import SUPERVISOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class SupervisorPlanningError(RuntimeError):
    """Supervisor 规划失败"""


class ResearchSupervisor:
    """通过 LLM 结构化输出生成经过验证的研究计划"""

    def __init__(
        self,
        *,
        llm,
        validator: PlanValidator,
        plan_service,
        approval_policy,
        approval_service=None,
        hook_bus=None,
        registry=None,
        max_steps: int = 12,
        max_tokens: int = 20_000,
        max_cost_microunits: int = 500_000,
    ):
        """初始化 Supervisor

        参数:
            llm: LLMClient 实例
            validator: PlanValidator 实例
            plan_service: PlanService 实例
            approval_policy: ApprovalPolicy 实例
            approval_service: ApprovalService 实例
            hook_bus: HookBus 实例
            registry: 可选 ResearchToolRegistry，用于动态构建工具目录
            max_steps: 最大步骤数
            max_tokens: 最大 token 数
            max_cost_microunits: 最大成本微单位
        """
        self._llm = llm
        self._validator = validator
        self._plan_service = plan_service
        self._approval_policy = approval_policy
        self._approval_service = approval_service
        self._hooks = hook_bus
        self._registry = registry
        self._budget_limits = BudgetLimits(
            max_steps=max_steps,
            max_tokens=max_tokens,
            max_cost_microunits=max_cost_microunits,
        )

    async def plan(
        self,
        db: AsyncSession,
        snapshot: TaskSnapshot,
        task_service,
    ) -> PlanningResult:
        """生成、验证并持久化研究计划

        参数:
            db: 异步数据库会话
            snapshot: 任务快照
            task_service: ResearchTaskService（用于状态转换）

        返回:
            PlanningResult
        """
        from src.research.schemas import ResearchTaskStatus

        # 转换到 planning
        await task_service.transition(
            db, snapshot.task_id, snapshot.workspace_id,
            expected={ResearchTaskStatus.SUBMITTED},
            target=ResearchTaskStatus.PLANNING,
        )

        # 从注册表动态构建工具目录
        if self._registry is not None:
            tool_defs = self._registry.list_tools()
            tool_catalog = ", ".join(t.name for t in tool_defs)
        else:
            tool_catalog = "knowledge.search, web.search"

        # LLM 结构化输出
        prompt = SUPERVISOR_SYSTEM_PROMPT.format(
            question=snapshot.question,
            tool_catalog=tool_catalog,
            max_steps=self._budget_limits.max_steps,
            max_tokens=self._budget_limits.max_tokens,
            max_cost_microunits=self._budget_limits.max_cost_microunits,
        )
        draft = await self._llm.ainvoke_structured(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": snapshot.question},
            ],
            schema=PlanDraft,
            temperature=0.1,
        )

        # 验证
        self._validator.validate(draft, limits=self._budget_limits)

        # 评估审批
        requires_approval = self._approval_policy.evaluate(
            first_use=True,
            estimated_cost=draft.estimated_cost_microunits,
        )

        # 持久化
        plan = await self._plan_service.persist(
            db,
            workspace_id=snapshot.workspace_id,
            task_id=snapshot.task_id,
            draft=draft,
        )

        # 发射 AFTER_PLAN Hook
        if self._hooks is not None:
            from src.governance.hooks import CriticalHookError, HookEvent
            try:
                await self._hooks.emit(
                    HookEvent.AFTER_PLAN,
                    {"task_id": snapshot.task_id, "version": plan.version},
                )
            except CriticalHookError:
                await task_service.transition(
                    db, snapshot.task_id, snapshot.workspace_id,
                    expected={ResearchTaskStatus.PLANNING},
                    target=ResearchTaskStatus.FAILED,
                    error="AFTER_PLAN Hook 拒绝",
                )
                raise SupervisorPlanningError("AFTER_PLAN Hook 拒绝")

        # 转换状态并激活步骤
        if requires_approval:
            await task_service.transition(
                db, snapshot.task_id, snapshot.workspace_id,
                expected={ResearchTaskStatus.PLANNING},
                target=ResearchTaskStatus.AWAITING_APPROVAL,
            )
        else:
            await task_service.transition(
                db, snapshot.task_id, snapshot.workspace_id,
                expected={ResearchTaskStatus.PLANNING},
                target=ResearchTaskStatus.RUNNING,
            )

        logger.info("Supervisor: plan created for task %s version=%d approved=%s",
                     snapshot.task_id, plan.version, requires_approval)

        return PlanningResult(
            task_id=snapshot.task_id,
            plan=draft,
            requires_approval=requires_approval,
            approval_reason=(
                "first_use" if requires_approval else ""
            ),
        )
