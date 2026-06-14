"""
PostgreSQL controlled benchmark test.
验证基准测试写入真实 PostgreSQL 行并完成步骤。
"""
import os

import pytest
from sqlalchemy import func, select

from src.models.research_execution import ResearchStep
from src.research.benchmark import BenchmarkConfig, run_full_benchmark


@pytest.mark.asyncio
async def test_postgres_benchmark_persists_and_completes_steps(postgres_engine, postgres_schema):
    """验证基准测试写入真实 PG 行并完成步骤"""
    config = BenchmarkConfig(
        database_url=os.environ["TEST_DATABASE_URL"],
        worker_counts=[1],
        task_count=3,
        seed=7,
    )
    results = await run_full_benchmark(config, scenarios=["normal"])
    assert len(results) == 1
    assert results[0].benchmark_kind == "postgresql_controlled_harness"
    assert results[0].database_dialect == "postgresql"
    assert results[0].success_count == 3
    assert results[0].duplicate_claim_count == 0

    async with postgres_engine.connect() as conn:
        completed = await conn.scalar(
            select(func.count()).select_from(ResearchStep)
            .where(
                ResearchStep.id.like("BENCH-%"),
                ResearchStep.status == "completed",
            )
        )
    assert completed >= 3
