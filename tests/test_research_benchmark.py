"""
研究基准测试模型和运行器测试
验证 BenchmarkConfig、BenchmarkTaskResult、BenchmarkResult 及 percentiles 计算。
"""
import pytest

from src.research.benchmark import (
    BenchmarkConfig,
    BenchmarkResult,
    BenchmarkTaskResult,
    _percentile,
    run_benchmark_scenario,
    run_full_benchmark,
)


def test_benchmark_config_defaults():
    """验证 BenchmarkConfig 默认值"""
    c = BenchmarkConfig()
    assert c.worker_counts == [1, 2, 4, 8]
    assert c.task_count == 10
    assert c.timeout_seconds == 30
    assert c.fake_latency_range == (0.05, 0.3)


def test_benchmark_task_result_fields():
    """验证 BenchmarkTaskResult 字段"""
    r = BenchmarkTaskResult(
        task_id="t1", worker_count=4, scenario="normal", success=True, latency_s=0.5
    )
    assert r.success is True
    assert r.error is None


def test_percentile_empty():
    """验证空列表百分位返回 0.0"""
    assert _percentile([], 50) == 0.0


def test_percentile_exact():
    """验证百分位计算准确性"""
    data = sorted([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    assert _percentile(data, 50) == pytest.approx(5.5)
    assert _percentile(data, 0) == 1.0
    assert _percentile(data, 100) == 10.0


@pytest.mark.asyncio
async def test_normal_scenario_succeeds():
    """验证正常场景的任务成功执行"""
    import asyncio

    config = BenchmarkConfig(worker_counts=[1], task_count=3)
    semaphore = asyncio.Semaphore(1)
    result = await run_benchmark_scenario(config, "normal", 1, semaphore)
    assert result.scenario == "normal"
    assert result.success_count == 3
    assert result.failure_count == 0
    assert result.task_count == 3
    assert result.p50_latency_s > 0


@pytest.mark.asyncio
async def test_full_benchmark_runs_all_scenarios():
    """验证完整基准测试运行所有场景"""
    config = BenchmarkConfig(worker_counts=[1, 2], task_count=2)
    results = await run_full_benchmark(config)
    # 4 scenarios x 2 worker counts = 8 results
    assert len(results) == 8
    scenarios = {r.scenario for r in results}
    assert "normal" in scenarios
    assert "timeout" in scenarios
    assert "execution_error" in scenarios
    assert "rate_limited" in scenarios


@pytest.mark.asyncio
async def test_timeout_scenario_has_failures():
    """验证超时场景产生失败任务"""
    import asyncio

    config = BenchmarkConfig(worker_counts=[1], task_count=2, timeout_seconds=1)
    semaphore = asyncio.Semaphore(1)
    result = await run_benchmark_scenario(config, "timeout", 1, semaphore)
    # timeout pipeline sleeps 5s, so with 1s timeout all should fail
    assert result.failure_count > 0
    for r in result.results:
        if not r.success:
            assert "TimeoutError" in r.error or "timeout" in r.error.lower() or "simulated" in r.error.lower() or r.error == "TimeoutError"


@pytest.mark.asyncio
async def test_error_scenario_has_failures():
    """验证执行错误场景产生失败任务"""
    import asyncio

    config = BenchmarkConfig(worker_counts=[1], task_count=2)
    semaphore = asyncio.Semaphore(1)
    result = await run_benchmark_scenario(config, "execution_error", 1, semaphore)
    assert result.failure_count > 0
    for r in result.results:
        if not r.success:
            assert "simulated execution error" in r.error


@pytest.mark.asyncio
async def test_rate_limited_scenario_has_failures():
    """验证限流场景产生失败任务"""
    import asyncio

    config = BenchmarkConfig(worker_counts=[1], task_count=2)
    semaphore = asyncio.Semaphore(1)
    result = await run_benchmark_scenario(config, "rate_limited", 1, semaphore)
    assert result.failure_count > 0
    for r in result.results:
        if not r.success:
            assert "rate limit" in r.error.lower()


@pytest.mark.asyncio
async def test_benchmark_result_throughput():
    """验证吞吐量计算合理"""
    import asyncio

    config = BenchmarkConfig(worker_counts=[4], task_count=5, timeout_seconds=10)
    semaphore = asyncio.Semaphore(4)
    result = await run_benchmark_scenario(config, "normal", 4, semaphore)
    assert result.throughput_tasks_per_sec > 0
    assert result.total_duration_s > 0


@pytest.mark.asyncio
async def test_scenario_names_are_consistent():
    """验证场景名称在各结果中一致"""
    config = BenchmarkConfig(worker_counts=[1, 4], task_count=2)
    results = await run_full_benchmark(config, scenarios=["normal", "timeout"])
    for r in results:
        assert r.scenario in ("normal", "timeout")
        assert r.worker_count in (1, 4)
