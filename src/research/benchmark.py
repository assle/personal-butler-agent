"""
研究管线基准测试
使用真实 PostgreSQL 任务/计划/步骤记录和 ResearchStepService.claim_next()
测量并发认领吞吐量和延迟。外部依赖使用可控 fake provider。
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.models.research import ResearchTask
from src.models.research_execution import ResearchPlan, ResearchStep
from src.models.workspace import Workspace
from src.research.schemas import ResearchStepStatus
from src.research.steps import ResearchStepService


@dataclass
class BenchmarkConfig:
    """基准测试配置"""

    database_url: str
    worker_counts: list[int] = field(default_factory=lambda: [1, 3, 5])
    task_count: int = 12
    seed: int = 7
    timeout_seconds: int = 10
    normal_latency_ms: int = 25
    timeout_latency_ms: int = 100


@dataclass
class BenchmarkTaskResult:
    """单个任务基准测试结果"""

    task_id: str
    worker_count: int
    scenario: str
    success: bool
    latency_s: float
    error: Optional[str] = None


@dataclass
class BenchmarkResult:
    """基准测试汇总结果"""

    scenario: str
    worker_count: int
    task_count: int
    success_count: int
    failure_count: int
    total_duration_s: float
    p50_latency_s: float
    p90_latency_s: float
    p99_latency_s: float
    mean_latency_s: float
    throughput_tasks_per_sec: float
    benchmark_kind: str = "postgresql_controlled_harness"
    database_dialect: str = "postgresql"
    external_dependencies: str = "fake"
    retry_count: int = 0
    duplicate_claim_count: int = 0
    results: list[BenchmarkTaskResult] = field(default_factory=list)


def _percentile(sorted_values: list[float], pct: float) -> float:
    """计算百分位值

    参数:
        sorted_values: 已排序的数据列表
        pct: 百分位 (0-100)

    返回:
        float: 对应百分位的值
    """
    if not sorted_values:
        return 0.0
    idx = int(len(sorted_values) * pct / 100)
    return sorted_values[min(idx, len(sorted_values) - 1)]


async def _seed_benchmark_steps(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: str,
    task_count: int,
) -> str:
    """播种基准测试步骤

    创建 Workspace、ResearchTask、ResearchPlan 和 ResearchStep 记录。

    参数:
        session_factory: 异步会话工厂
        run_id: 运行标识
        task_count: 步骤数

    返回:
        str: 任务 ID
    """
    workspace_id = f"bench-{run_id}"
    task_id = f"BENCH-{run_id}"
    async with session_factory() as db:
        db.add(Workspace(id=workspace_id, name=f"Benchmark {run_id}", status="active"))
        await db.flush()
        db.add(ResearchTask(
            id=task_id,
            source_msgid=f"bench-msg-{run_id}",
            requester_open_userid="benchmark",
            workspace_id=workspace_id,
            question="controlled benchmark",
            research_type="benchmark",
            status="running",
            access_scope={"workspace_id": workspace_id},
            max_rounds=1,
            timeout_seconds=60,
            current_round=0,
            cancel_requested=False,
        ))
        await db.flush()
        plan = ResearchPlan(
            workspace_id=workspace_id,
            task_id=task_id,
            version=1,
            objective="controlled benchmark",
            completion_criteria=["all steps terminal"],
            estimated_cost_microunits=0,
            estimated_tokens=0,
            raw_plan={"benchmark": True},
        )
        db.add(plan)
        await db.flush()
        for index in range(task_count):
            db.add(ResearchStep(
                id=f"{task_id}:{index:04d}",
                workspace_id=workspace_id,
                task_id=task_id,
                plan_id=plan.id,
                kind="benchmark",
                tool_name="benchmark.fake",
                input_payload={"index": index},
                status=ResearchStepStatus.READY.value,
                idempotency_key=f"{task_id}:{index:04d}",
                max_attempts=2,
            ))
        await db.commit()
    return task_id


async def _run_controlled_scenario(
    scenario: str,
    *,
    normal_latency_ms: int,
    timeout_latency_ms: int,
) -> None:
    """模拟受控场景的假执行

    参数:
        scenario: 场景名称
        normal_latency_ms: 正常延迟毫秒数
        timeout_latency_ms: 超时延迟毫秒数
    """
    if scenario == "normal":
        await asyncio.sleep(normal_latency_ms / 1000)
        return
    if scenario == "timeout":
        await asyncio.sleep(timeout_latency_ms / 1000)
        raise asyncio.TimeoutError("controlled provider timeout")
    if scenario == "execution_error":
        raise RuntimeError("controlled provider execution error")
    if scenario == "rate_limited":
        raise RuntimeError("controlled provider rate limit")
    raise ValueError(f"unsupported benchmark scenario: {scenario}")


@dataclass
class _BenchmarkRunState:
    """基准测试运行内部状态"""

    results: list[BenchmarkTaskResult] = field(default_factory=list)
    claimed_step_ids: set[str] = field(default_factory=set)
    duplicate_claim_count: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def _run_benchmark_worker(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_id: str,
    worker_id: str,
    worker_count: int,
    scenario: str,
    config: BenchmarkConfig,
    state: _BenchmarkRunState,
) -> None:
    """运行单个基准测试 worker

    使用 ResearchStepService.claim_next() 认领步骤，
    执行受控场景，然后完成步骤。

    参数:
        session_factory: 异步会话工厂
        task_id: 任务 ID
        worker_id: Worker 标识
        worker_count: 总 worker 数
        scenario: 场景名称
        config: 基准测试配置
        state: 运行状态
    """
    step_service = ResearchStepService()
    while True:
        async with session_factory() as db:
            claimed = await step_service.claim_next(
                db, owner=worker_id, limit=1, task_id=task_id,
            )
            if not claimed:
                await db.rollback()
                return
            step_id = claimed[0].id
            await db.commit()

        async with state.lock:
            if step_id in state.claimed_step_ids:
                state.duplicate_claim_count += 1
            state.claimed_step_ids.add(step_id)

        started = time.monotonic()
        error = None
        try:
            await asyncio.wait_for(
                _run_controlled_scenario(
                    scenario,
                    normal_latency_ms=config.normal_latency_ms,
                    timeout_latency_ms=config.timeout_latency_ms,
                ),
                timeout=config.timeout_seconds,
            )
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        elapsed = time.monotonic() - started

        async with session_factory() as db:
            await step_service.complete_step(
                db,
                step_id,
                result_ref=f"benchmark://{task_id}/{step_id}" if error is None else None,
                error=error,
            )
            await db.commit()

        state.results.append(BenchmarkTaskResult(
            task_id=step_id,
            worker_count=worker_count,
            scenario=scenario,
            success=error is None,
            latency_s=elapsed,
            error=error,
        ))


async def _run_postgres_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    config: BenchmarkConfig,
    scenario: str,
    worker_count: int,
) -> BenchmarkResult:
    """在 PostgreSQL 上运行单个场景 x 并发数的基准测试

    播种步骤 → 启动 workers → 收集指标。

    参数:
        session_factory: 异步会话工厂
        config: 基准测试配置
        scenario: 场景名称
        worker_count: 并发 worker 数

    返回:
        BenchmarkResult: 测试结果汇总
    """
    run_id = uuid4().hex[:12]
    task_id = await _seed_benchmark_steps(
        session_factory, run_id=run_id, task_count=config.task_count,
    )
    state = _BenchmarkRunState()
    started = time.monotonic()
    await asyncio.gather(*[
        _run_benchmark_worker(
            session_factory,
            task_id=task_id,
            worker_id=f"{run_id}-worker-{idx}",
            worker_count=worker_count,
            scenario=scenario,
            config=config,
            state=state,
        )
        for idx in range(worker_count)
    ])
    total_duration = time.monotonic() - started

    async with session_factory() as db:
        terminal_count = await db.scalar(
            select(func.count()).select_from(ResearchStep).where(
                ResearchStep.task_id == task_id,
                ResearchStep.status.in_([
                    ResearchStepStatus.COMPLETED.value,
                    ResearchStepStatus.FAILED.value,
                ]),
            )
        )
    if terminal_count != config.task_count:
        raise RuntimeError(
            f"expected {config.task_count} terminal steps, got {terminal_count}"
        )

    results = sorted(state.results, key=lambda item: item.task_id)
    latencies = sorted(item.latency_s for item in results)
    success_count = sum(item.success for item in results)
    return BenchmarkResult(
        scenario=scenario,
        worker_count=worker_count,
        task_count=len(results),
        success_count=success_count,
        failure_count=len(results) - success_count,
        total_duration_s=total_duration,
        p50_latency_s=_percentile(latencies, 50),
        p90_latency_s=_percentile(latencies, 90),
        p99_latency_s=_percentile(latencies, 99),
        mean_latency_s=sum(latencies) / len(latencies) if latencies else 0.0,
        throughput_tasks_per_sec=len(results) / total_duration if total_duration else 0.0,
        retry_count=0,
        duplicate_claim_count=state.duplicate_claim_count,
        results=results,
    )


async def run_full_benchmark(
    config: BenchmarkConfig,
    scenarios: list[str] | None = None,
) -> list[BenchmarkResult]:
    """运行完整基准测试（所有场景 x 所有 worker 数）

    使用真实 PostgreSQL 连接和 ResearchStepService.claim_next()。

    参数:
        config: 基准测试配置
        scenarios: 要测试的场景列表，默认为 ["normal"]

    返回:
        list[BenchmarkResult]: 所有场景和 worker 数的测试结果
    """
    selected = scenarios or ["normal", "timeout", "execution_error", "rate_limited"]
    engine = create_async_engine(config.database_url, pool_pre_ping=True)
    try:
        if engine.dialect.name != "postgresql":
            raise ValueError("controlled benchmark requires postgresql+asyncpg")
        async with engine.connect():
            pass
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False,
        )
        results: list[BenchmarkResult] = []
        for scenario in selected:
            for wc in config.worker_counts:
                results.append(await _run_postgres_scenario(
                    session_factory, config=config, scenario=scenario, worker_count=wc,
                ))
        return results
    finally:
        await engine.dispose()
