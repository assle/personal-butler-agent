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
    run_full_benchmark,
)

# 不可路由的 URL，仅用于模型测试（不实际连接）
_UNREACHABLE_PG = "postgresql+asyncpg://invalid:invalid@127.0.0.1:1/missing"


def test_benchmark_config_defaults():
    """验证 BenchmarkConfig 默认值"""
    c = BenchmarkConfig(database_url=_UNREACHABLE_PG)
    assert c.worker_counts == [1, 3, 5]
    assert c.task_count == 12
    assert c.seed == 7
    assert c.timeout_seconds == 10
    assert c.normal_latency_ms == 25
    assert c.timeout_latency_ms == 100


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
    # 新实现使用整数索引: p50 -> idx=5 -> data[5]=6.0
    assert _percentile(data, 50) == pytest.approx(6.0)
    assert _percentile(data, 0) == 1.0
    assert _percentile(data, 100) == 10.0


def test_benchmark_result_provenance():
    """验证 BenchmarkResult 包含 provenance 字段"""
    r = BenchmarkResult(
        scenario="normal", worker_count=1, task_count=3,
        success_count=3, failure_count=0,
        total_duration_s=1.0, p50_latency_s=0.1, p90_latency_s=0.2,
        p99_latency_s=0.3, mean_latency_s=0.15,
        throughput_tasks_per_sec=3.0,
    )
    assert r.benchmark_kind == "postgresql_controlled_harness"
    assert r.database_dialect == "postgresql"
    assert r.external_dependencies == "fake"
    assert r.duplicate_claim_count == 0


@pytest.mark.asyncio
async def test_benchmark_rejects_unreachable_postgres():
    """验证 benchmark 不会忽略不可达的 database_url"""
    config = BenchmarkConfig(
        database_url="postgresql+asyncpg://invalid:invalid@127.0.0.1:1/missing",
        worker_counts=[1],
        task_count=1,
        seed=7,
    )
    with pytest.raises(Exception):
        await run_full_benchmark(config, scenarios=["normal"])
