"""
Taskiq 研究与投递任务
Taskiq wrapper 只接收 task_id；数据库会话和服务在 Worker 进程内重新创建。
"""
import asyncio
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select, update

from src.config import settings
from src.db.session import async_session
from src.llm.client import LLMClient
from src.models.research import ResearchReport
from src.models.research_execution import ResearchStep
from src.research.broker import broker
from src.research.delivery import ResearchDeliveryService
from src.research.dispatch import ResearchStepDispatcher
from src.research.evidence import ResearchEvidenceService
from src.research.execution import ResearchStepExecutor
from src.research.executor import FoundationResearchExecutor
from src.research.pipeline import ResearchPipelineCoordinator
from src.research.queue import TaskiqResearchDispatcher
from src.research.schemas import ResearchStepStatus, ResearchTaskStatus
from src.research.service import ResearchTaskService
from src.research.steps import ResearchStepService
from src.research.tools import ResearchToolDefinition, ResearchToolRegistry
from src.research.review.service import CitationReviewService
from src.research.synthesis.service import ReportSynthesisService
from src.wechat.app_client import (
    RedisAccessTokenCache,
    WeComAppMessageClient,
)

logger = logging.getLogger(__name__)


async def execute_research_job(
    task_id: str,
    *,
    session_factory,
    executor,
    dispatcher,
    task_service,
    timeout_seconds,
) -> None:
    """执行研究、提交报告，再派发独立投递任务"""
    async with session_factory() as db:
        try:
            async with asyncio.timeout(timeout_seconds):
                await executor.execute(db, task_id)
            await db.commit()
        except TimeoutError:
            await db.rollback()
            async with session_factory() as timeout_db:
                await task_service.mark_timed_out(
                    timeout_db,
                    task_id,
                    f"research exceeded {timeout_seconds} seconds",
                )
                await timeout_db.commit()
            raise
        except Exception as exc:
            await db.rollback()
            async with session_factory() as failed_db:
                await task_service.mark_failed(failed_db, task_id, str(exc))
                await failed_db.commit()
            raise
    await dispatcher.enqueue_delivery(task_id)


async def execute_delivery_job(
    task_id: str,
    *,
    session_factory,
    delivery_service,
    sleep=asyncio.sleep,
) -> None:
    """独立投递，指数退避重试三次"""
    last_error: Exception | None = None
    for attempt, delay in enumerate((0, 1, 2), start=1):
        if delay:
            await sleep(delay)
        async with session_factory() as db:
            try:
                await delivery_service.deliver(db, task_id)
                await db.commit()
                return
            except Exception as exc:
                last_error = exc
                await db.commit()
    assert last_error is not None
    raise last_error


_task_service = ResearchTaskService(
    max_rounds=settings.research_max_rounds,
    timeout_seconds=settings.research_timeout_seconds,
)
_redis_client = Redis.from_url(settings.redis_url)
_app_client = WeComAppMessageClient(
    corp_id=settings.wecom_app_corp_id,
    secret=settings.wecom_app_secret,
    agent_id=settings.wecom_app_agent_id,
    cache=RedisAccessTokenCache(_redis_client),
)
_executor = FoundationResearchExecutor(_task_service, LLMClient())
_delivery_service = ResearchDeliveryService(_task_service, _app_client)
_step_service = ResearchStepService(lease_seconds=settings.research_step_lease_seconds)

# Phase 3: 工具注册表与步骤执行器
_registry = ResearchToolRegistry()
_step_executor = ResearchStepExecutor(
    registry=_registry,
    evidence_service=ResearchEvidenceService(),
    step_service=_step_service,
)

# 注册内置研究工具使用真实依赖
from src.knowledge import KnowledgeService
from src.research.providers.builtin import register_builtin_research_tools, BuiltinResearchDependencies
from src.research.sources import ResearchSourceGateway
from src.search import WebSearchService
from src.research.web.fetcher import SecuredFetcher

register_builtin_research_tools(
    _registry,
    BuiltinResearchDependencies(
        source_gateway=ResearchSourceGateway(
            knowledge=KnowledgeService(),
            web=WebSearchService(),
        ),
        web_search_service=WebSearchService(),
        web_fetcher=SecuredFetcher(),
    ),
)

# Phase 3: Structured LLM Supervisor
from src.research.approvals import ApprovalPolicy, ApprovalService
from src.research.planning.service import PlanService
from src.research.planning.validator import PlanValidator
from src.research.supervisor import ResearchSupervisor

_supervisor = ResearchSupervisor(
    llm=LLMClient(),
    validator=PlanValidator.from_registry(_registry),
    plan_service=PlanService(),
    registry=_registry,
    approval_policy=ApprovalPolicy(high_cost_microunits=settings.research_high_cost_approval_microunits),
    approval_service=ApprovalService(
        ApprovalPolicy(high_cost_microunits=settings.research_high_cost_approval_microunits),
        _step_service,
    ),
)

# Phase 4: 报告综合与引用验证服务
_llm = LLMClient()
_synthesis_service = ReportSynthesisService(llm=_llm, task_service=_task_service)
_review_service = CitationReviewService(llm=_llm, task_service=_task_service)


@broker.task(task_name="research.deliver")
async def deliver_research_task(task_id: str) -> None:
    """Taskiq 报告投递入口"""
    await execute_delivery_job(
        task_id,
        session_factory=async_session,
        delivery_service=_delivery_service,
    )


@broker.task(task_name="research.run")
async def run_research_task(task_id: str) -> None:
    """Taskiq 研究执行入口"""
    dispatcher = TaskiqResearchDispatcher(
        run_research_task, deliver_research_task
    )
    await execute_research_job(
        task_id,
        session_factory=async_session,
        executor=_executor,
        dispatcher=dispatcher,
        task_service=_task_service,
        timeout_seconds=settings.research_timeout_seconds,
    )


async def execute_planning_job(
    task_id: str,
    *,
    session_factory,
    task_service,
    supervisor=None,
    step_service=None,
    step_dispatcher=None,
) -> None:
    """执行研究规划：LLM Supervisor 生成计划或 fixture 回退

    规划完成后使用 step_dispatcher 派发就绪步骤到队列。

    参数:
        task_id: 研究任务 ID
        session_factory: 数据库会话工厂
        task_service: 任务服务
        supervisor: 可选 LLM Supervisor（Phase 3）
        step_service: 步骤服务（用于激活无依赖步骤）
        step_dispatcher: 可选步骤派发器（用于派发就绪步骤到队列）
    """
    from src.research.planning.schemas import PlanDraft, StepDraft
    from src.research.planning.service import PlanService

    async with session_factory() as db:
        if supervisor is not None:
            # Phase 3: Structured LLM Supervisor
            from src.research.supervisor.planner import TaskSnapshot as _TaskSnapshot

            task = await task_service.get_task(db, task_id)
            from src.governance.workspaces import WorkspaceService

            workspace = await WorkspaceService().resolve_member(
                db,
                task.requester_open_userid,
                workspace_id=task.workspace_id,
            )
            snapshot = _TaskSnapshot(
                task_id=task_id,
                workspace_id=task.workspace_id,
                question=task.question,
                user_id=task.requester_open_userid,
                member_id=workspace.member_id,
                role=workspace.role,
                research_approved_once=workspace.research_approved_once,
            )
            result = await supervisor.plan(db, snapshot, task_service)

            if not result.requires_approval and step_service is not None:
                await step_service.mark_root_steps_ready(db, task_id)
        else:
            # Phase 2: 确定性 fixture planner（回退）
            task = await task_service.get_task(db, task_id)
            await task_service.transition(
                db, task_id, task.workspace_id,
                expected={ResearchTaskStatus.SUBMITTED},
                target=ResearchTaskStatus.PLANNING,
            )

            draft = PlanDraft(
                objective=task.question,
                completion_criteria=["回答用户问题"],
                estimated_tokens=500,
                estimated_cost_microunits=1000,
                steps=[
                    StepDraft(
                        key="search",
                        kind="knowledge_retrieval",
                        tool_name="knowledge.search",
                        input_payload={"query": task.question},
                    ),
                ],
            )

            service = PlanService()
            plan = await service.persist(
                db, workspace_id=task.workspace_id,
                task_id=task_id, draft=draft,
            )

            # 检查是否需要审批
            from src.research.approvals import ApprovalPolicy, ApprovalService
            from src.research.steps import ResearchStepService
            from src.governance.workspaces import WorkspaceContext

            policy = ApprovalPolicy(high_cost_microunits=250_000)
            step_svc = ResearchStepService(lease_seconds=120)
            approval_service = ApprovalService(policy, step_svc)

            ws_ctx = WorkspaceContext(
                workspace_id=task.workspace_id,
                member_id=0,  # planning不需要完整member上下文
                open_userid=task.requester_open_userid,
                role="member",
                research_approved_once=True,  # Phase 2 fixture默认已审批
            )

            approval = await approval_service.request_approval(
                db, task=task, plan=plan, workspace=ws_ctx,
            )
            if approval is None:
                # 无需审批，直接激活步骤
                await task_service.transition(
                    db, task_id, task.workspace_id,
                    expected={ResearchTaskStatus.PLANNING},
                    target=ResearchTaskStatus.RUNNING,
                )
                await step_svc.mark_root_steps_ready(db, task_id)

        await db.commit()

    # 规划完成后派发就绪步骤到队列
    if step_dispatcher is not None:
        await step_dispatcher.dispatch_ready(task_id)


async def execute_step_job(
    step_id: str,
    *,
    session_factory,
    step_service,
    executor=None,
    dispatcher=None,
    step_dispatcher=None,
    pipeline=None,
) -> None:
    """执行单个研究步骤

    步骤执行完毕后使用 pipeline 协调器检查是否需要进入综合阶段。

    参数:
        step_id: 步骤 ID
        session_factory: 数据库会话工厂
        step_service: 步骤服务
        executor: 可选步骤执行器（Phase 3），不为 None 时执行真实工具调用
        dispatcher: 保留参数，当前通过 pipeline 协调器派发综合任务
        step_dispatcher: 可选步骤派发器，用于派发本步骤解锁的后续步骤
        pipeline: 可选 ResearchPipelineCoordinator，用于步骤完成后检查并派发综合
    """
    async with session_factory() as db:
        step = await db.get(ResearchStep, step_id)
        if step is None or step.status != ResearchStepStatus.RUNNING.value:
            return

        task_id = step.task_id  # 在 commit 前保存，避免过期对象访问
        lease_owner = step.owner

        try:
            if executor is not None:
                result = await executor.execute(db, step_id, lease_owner or "")
                if not result.success:
                    logger.error("Step %s failed: %s", step_id, result.error)
            else:
                # Phase 2 fixture 回退: 步骤直接成功
                await step_service.complete_step(
                    db, step_id, result_ref=f"fixture_result:{step_id}",
                )
            await db.commit()
        except Exception as exc:
            await db.rollback()
            async with session_factory() as fail_db:
                await step_service.complete_step(
                    fail_db, step_id, error=str(exc),
                )
                await fail_db.commit()
            return

        # 当前步骤可能解锁新的 DAG 节点，提交状态后继续认领并派发。
        if step_dispatcher is not None:
            await step_dispatcher.dispatch_ready(task_id)

        # 使用 pipeline 协调器检查是否全部步骤完成并派发综合
        if pipeline is not None:
            await pipeline.queue_synthesis_if_complete(db, task_id)


async def execute_lease_recovery_job(
    *,
    session_factory,
    step_service,
) -> None:
    """恢复过期租约的步骤"""
    async with session_factory() as db:
        recovered = await step_service.recover_expired_leases(db)
        if recovered:
            await db.commit()


@broker.task(task_name="research.plan")
async def plan_research_task(task_id: str) -> None:
    """Taskiq 研究规划入口

    Phase 3: 使用 LLM Supervisor 生成计划并处理审批。
    Phase 2 回退: 使用确定性 fixture planner。
    规划完成后通过 step_dispatcher 派发就绪步骤。
    """
    await execute_planning_job(
        task_id,
        session_factory=async_session,
        task_service=_task_service,
        supervisor=_supervisor,
        step_service=_step_service,
        step_dispatcher=_step_dispatcher,
    )


@broker.task(task_name="research.step")
async def run_research_step(step_id: str) -> None:
    """Taskiq 研究步骤入口"""
    await execute_step_job(
        step_id,
        session_factory=async_session,
        step_service=_step_service,
        executor=_step_executor,
        dispatcher=_dispatcher,
        step_dispatcher=_step_dispatcher,
        pipeline=_pipeline,
    )


@broker.task(task_name="research.recover_leases")
async def recover_research_leases() -> None:
    """Taskiq 过期步骤租约恢复入口"""
    await execute_lease_recovery_job(
        session_factory=async_session,
        step_service=_step_service,
    )


@broker.task(task_name="research.synthesize")
async def synthesize_research_task(task_id: str) -> None:
    """Taskiq 报告综合入口"""
    async with async_session() as db:
        try:
            report = await _synthesis_service.synthesize(db, task_id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("Synthesis failed for %s: %s", task_id, exc)
            raise
    # 综合完成后由协调器进入验证阶段
    async with async_session() as db:
        await _pipeline.queue_validation(db, task_id)


@broker.task(task_name="research.validate")
async def validate_research_task(task_id: str) -> None:
    """Taskiq 引用验证入口"""
    async with async_session() as db:
        try:
            decision = await _review_service.review(db, task_id)
            await db.commit()
            if decision.outcome == "pass":
                await _pipeline.complete_and_queue_delivery(db, task_id)
            elif decision.outcome == "repair":
                task = await _task_service.get_task(db, task_id)
                from src.research.quality import QualityRepairCoordinator
                from src.research.planning.service import PlanService
                coordinator = QualityRepairCoordinator(
                    task_service=_task_service,
                    plan_service=PlanService(),
                    max_repair_rounds=1,
                )
                result = await coordinator.handle(db, task_id, decision)
                if result.new_step_ids:
                    await _pipeline.repair_and_retry(db, task_id, result.new_step_ids)
                elif result.failed:
                    await _task_service.mark_failed(db, task_id, "质量修复超出最大轮次")
                    await db.commit()
                else:
                    # "weaken" — 弱化声明后直接完成验证
                    await _pipeline.complete_and_queue_delivery(db, task_id)
            else:  # fail
                await _task_service.mark_failed(db, task_id, "Citation review failed")
                await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("Validation failed for %s: %s", task_id, exc)
            raise


# 在全部 broker task 定义之后创建模块级派发器，使 execute_step_job 可引用
_dispatcher = TaskiqResearchDispatcher(
    run_task=run_research_task,
    deliver_task=deliver_research_task,
    plan_task=plan_research_task,
    step_task=run_research_step,
    synthesis_task=synthesize_research_task,
    validation_task=validate_research_task,
)

# 步骤派发器与管线协调器（需在 _dispatcher 之后创建）
_step_dispatcher = ResearchStepDispatcher(
    step_service=_step_service,
    dispatcher=_dispatcher,
    session_factory=async_session,
    max_concurrent=settings.research_max_concurrent_steps,
)

_pipeline = ResearchPipelineCoordinator(
    task_service=_task_service,
    dispatcher=_dispatcher,
    synthesis_dispatcher=_dispatcher,
    validation_dispatcher=_dispatcher,
    delivery_dispatcher=_dispatcher,
    step_dispatcher=_dispatcher,
)
