"""
研究管道基准测试
模拟高并发场景下研究任务的执行，测量延迟、成功率和吞吐量。

Workflow:
1. BenchmarkConfig 配置并发度、任务数、超时等参数
2. BenchmarkTask 模拟研究任务生命周期（计划 → 执行 → 综合 → 验证）
3. BenchmarkRunner 使用 async semaphore 控制并发并收集指标
4. 结果按百分位汇总并包含失败场景标记
"""
import asyncio
import math
import random
import time
from dataclasses import dataclass, field
from statistics import median
from typing import Callable


@dataclass
class BenchmarkConfig:
    """基准测试配置"""

    database_url: str = "sqlite+aiosqlite:///:memory:"
    worker_counts: list[int] = field(default_factory=lambda: [1, 2, 4, 8])
    task_count: int = 10
    timeout_seconds: int = 30
    fake_latency_range: tuple[float, float] = (0.05, 0.3)  # 秒
    failure_rate: float = 0.1


@dataclass
class BenchmarkTaskResult:
    """单个任务基准测试结果"""

    task_id: str
    worker_count: int
    scenario: str
    success: bool
    latency_s: float
    error: str | None = None


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
    results: list[BenchmarkTaskResult] = field(default_factory=list)


def _percentile(sorted_data: list[float], p: float) -> float:
    """计算百分位值

    参数:
        sorted_data: 已排序的数据列表
        p: 百分位 (0-100)

    返回:
        float: 对应百分位的值
    """
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * p / 100
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


async def _fake_plan(task_id: str) -> float:
    """模拟计划阶段"""
    await asyncio.sleep(random.uniform(0.02, 0.1))
    return random.uniform(0.02, 0.1)


async def _fake_execute(task_id: str) -> float:
    """模拟执行阶段"""
    await asyncio.sleep(random.uniform(0.02, 0.15))
    return random.uniform(0.02, 0.15)


async def _fake_synthesize(task_id: str) -> float:
    """模拟综合阶段"""
    await asyncio.sleep(random.uniform(0.01, 0.05))
    return random.uniform(0.01, 0.05)


async def _fake_validate(task_id: str) -> float:
    """模拟验证阶段"""
    await asyncio.sleep(random.uniform(0.01, 0.03))
    return random.uniform(0.01, 0.03)


async def _fake_normal_pipeline(task_id: str) -> float:
    """模拟正常管道延迟"""
    await _fake_plan(task_id)
    await _fake_execute(task_id)
    await _fake_synthesize(task_id)
    await _fake_validate(task_id)
    return sum(
        [
            random.uniform(0.02, 0.1),  # plan
            random.uniform(0.02, 0.15),  # execute
            random.uniform(0.01, 0.05),  # synthesize
            random.uniform(0.01, 0.03),  # validate
        ]
    )


async def _fake_timeout_pipeline(task_id: str) -> float:
    """模拟超时失败场景"""
    await asyncio.sleep(5)  # 超时
    raise asyncio.TimeoutError("simulated timeout")


async def _fake_error_pipeline(task_id: str) -> float:
    """模拟执行错误场景"""
    await _fake_plan(task_id)
    raise RuntimeError("simulated execution error")


async def _fake_rate_limited_pipeline(task_id: str) -> float:
    """模拟限流失败场景"""
    raise RuntimeError("429 rate limit exceeded")


SCENARIOS: dict[str, Callable] = {
    "normal": _fake_normal_pipeline,
    "timeout": _fake_timeout_pipeline,
    "execution_error": _fake_error_pipeline,
    "rate_limited": _fake_rate_limited_pipeline,
}


async def run_benchmark_scenario(
    config: BenchmarkConfig,
    scenario: str,
    worker_count: int,
    semaphore: asyncio.Semaphore,
) -> BenchmarkResult:
    """运行指定场景和并发数的基准测试

    参数:
        config: 基准测试配置
        scenario: 场景名称
        worker_count: 并发 worker 数
        semaphore: 异步信号量

    返回:
        BenchmarkResult: 测试结果汇总
    """
    pipeline = SCENARIOS.get(scenario, _fake_normal_pipeline)
    started = time.monotonic()

    async def _run_task(task_idx: int) -> BenchmarkTaskResult:
        async with semaphore:
            t0 = time.monotonic()
            try:
                await asyncio.wait_for(
                    pipeline(f"bench-{scenario}-{task_idx}"),
                    timeout=config.timeout_seconds,
                )
                elapsed = time.monotonic() - t0
                return BenchmarkTaskResult(
                    task_id=f"bench-{scenario}-{task_idx}",
                    worker_count=worker_count,
                    scenario=scenario,
                    success=True,
                    latency_s=elapsed,
                )
            except Exception as exc:
                elapsed = time.monotonic() - t0
                return BenchmarkTaskResult(
                    task_id=f"bench-{scenario}-{task_idx}",
                    worker_count=worker_count,
                    scenario=scenario,
                    success=False,
                    latency_s=elapsed,
                    error=str(exc) or type(exc).__name__,
                )

    results = await asyncio.gather(
        *[_run_task(i) for i in range(config.task_count)]
    )
    total_duration = time.monotonic() - started

    success_results = [r for r in results if r.success]
    success_latencies = sorted(r.latency_s for r in success_results)
    all_latencies = sorted(r.latency_s for r in results)

    return BenchmarkResult(
        scenario=scenario,
        worker_count=worker_count,
        task_count=len(results),
        success_count=len(success_results),
        failure_count=len(results) - len(success_results),
        total_duration_s=total_duration,
        p50_latency_s=_percentile(all_latencies, 50),
        p90_latency_s=_percentile(all_latencies, 90),
        p99_latency_s=_percentile(all_latencies, 99),
        mean_latency_s=sum(all_latencies) / len(all_latencies) if all_latencies else 0.0,
        throughput_tasks_per_sec=len(results) / total_duration if total_duration > 0 else 0.0,
        results=results,
    )


async def run_full_benchmark(
    config: BenchmarkConfig,
    scenarios: list[str] | None = None,
) -> list[BenchmarkResult]:
    """运行完整基准测试（所有场景 x 所有 worker 数）

    参数:
        config: 基准测试配置
        scenarios: 要测试的场景列表，默认为 ["normal"]

    返回:
        list[BenchmarkResult]: 所有场景和 worker 数的测试结果
    """
    if scenarios is None:
        scenarios = ["normal", "timeout", "execution_error", "rate_limited"]

    all_results: list[BenchmarkResult] = []
    for scenario in scenarios:
        for workers in config.worker_counts:
            semaphore = asyncio.Semaphore(workers)
            result = await run_benchmark_scenario(config, scenario, workers, semaphore)
            all_results.append(result)
    return all_results
