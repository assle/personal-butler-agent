# Interview-Readiness Corrective Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the failed PostgreSQL gate, replace misleading evaluation and benchmark evidence with explicit reproducible provenance, correct interview materials against the code, and rerun the Week 4 acceptance audit.

**Architecture:** Keep the existing research pipeline and offline evaluator. Make the trace migration portable, add provenance that distinguishes fixture-derived quality data from measured runtime data, and replace the sleep-only benchmark with a PostgreSQL-backed controlled harness using real research task/plan/step rows and `ResearchStepService.claim_next()`. Documentation may claim only what the resulting tests and versioned artifacts prove.

**Tech Stack:** Python 3.13+, SQLAlchemy 2 async, Alembic, PostgreSQL 16, Redis 7, pytest, Pydantic v2, GitHub Actions, Markdown

---

## Current Audit Baseline

The corrective work starts from commit `f90dcfa`.

Fresh verification on June 14, 2026 showed:

- unit suite: `291 passed, 12 skipped`;
- integration suite: `6 failed, 7 passed`;
- latest GitHub Actions run `27485574895`: unit job passed, integration job
  failed during `alembic upgrade head`;
- `alembic/versions/add_trace_id_20260613.py` uses PostgreSQL-incompatible
  `randomblob()`;
- offline evaluation calculates metrics from fixture artifacts and does not
  call DeepSeek or execute the research pipeline;
- the benchmark accepts `database_url` but does not connect to a database;
- the required `artifacts/evaluation/2026-06-interview-baseline.json` and
  `artifacts/benchmarks/2026-06-interview-baseline.json` do not exist;
- interview documents contain code-level inaccuracies.

Do not mark the corrective plan complete until every gate in Task 5 passes.

## Scope Rules

- Do not add new chat capabilities.
- Do not add live DeepSeek calls to ordinary tests or CI.
- Keep the quality evaluator offline and deterministic.
- The PostgreSQL benchmark must use real PostgreSQL rows and transactions but
  fake external providers; label it a controlled harness, not production load.
- In benchmark output, `task_count` means the number of independently claimed
  `ResearchStep` work items inside one benchmark `ResearchTask`; document this
  distinction anywhere the metric is presented.
- Do not claim exactly-once delivery, production QPS, production users, or
  factual-answer accuracy.
- Do not delete legacy artifacts during this plan. Stop referencing them from
  current interview documents after the new artifacts are generated.
- Keep `CLAUDE.md` and `AGENTS.md` byte-for-byte identical.
- Do not modify or remove
  `.claude/worktrees/phase1-postgres-governance` or the untracked `dump.rdb`.
- Every changed Python function or method must retain the required Chinese
  purpose, parameter, and return-value documentation.

## File Map

**Modify**

- `alembic/versions/add_trace_id_20260613.py`
- `tests/integration/test_postgres_schema.py`
- `src/research/evaluation/schemas.py`
- `src/cli/evaluate_research.py`
- `tests/test_research_evaluation.py`
- `src/research/benchmark.py`
- `src/cli/benchmark_research.py`
- `tests/test_research_benchmark.py`
- `docs/interview/project-brief.md`
- `docs/interview/architecture.md`
- `docs/interview/demo-script.md`
- `docs/interview/metrics.md`
- `docs/interview/star-stories.md`
- `docs/interview/question-bank.md`
- `PROJECT_STUDY_GUIDE.md`
- `docs/agent/active-context.md`
- `docs/agent/upgrade-roadmap.md`
- `docs/agent/troubleshooting.md`
- `docs/operations/research-runbook.md`
- `docs/superpowers/plans/2026-06-13-interview-readiness-remediation-master.md`

**Create**

- `alembic/versions/repair_trace_id_20260614.py`
- `tests/integration/test_research_benchmark_postgres.py`
- `artifacts/benchmarks/.gitkeep`
- `artifacts/evaluation/2026-06-interview-baseline.json`
- `artifacts/benchmarks/2026-06-interview-baseline.json`

## Task 1: Repair the PostgreSQL Trace Migration

**Files:**

- Modify: `alembic/versions/add_trace_id_20260613.py`
- Create: `alembic/versions/repair_trace_id_20260614.py`
- Modify: `tests/integration/test_postgres_schema.py`
- Modify: `docs/agent/troubleshooting.md`

- [ ] **Step 1: Add migration regression coverage**

Extend `test_alembic_upgrade_applies_schema()` in
`tests/integration/test_postgres_schema.py` after the table assertions:

```python
    async with postgres_engine.connect() as conn:
        task_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]: column
                for column in sa_inspect(sync_conn).get_columns(
                    "research_tasks"
                )
            }
        )
        event_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]: column
                for column in sa_inspect(sync_conn).get_columns(
                    "research_events"
                )
            }
        )

    assert task_columns["trace_id"]["nullable"] is False
    assert event_columns["trace_id"]["nullable"] is False
```

Add a source-level regression test to the same module:

```python
def test_trace_migration_has_postgresql_backfill():
    """验证 trace 迁移不再把 SQLite randomblob 用于 PostgreSQL"""
    migration = Path(
        "alembic/versions/add_trace_id_20260613.py"
    ).read_text()
    assert 'if dialect == "postgresql":' in migration
    assert "md5(id)" in migration
```

Import `Path` from `pathlib`.

- [ ] **Step 2: Reproduce the PostgreSQL migration failure**

```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run alembic downgrade base

DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run alembic upgrade head
```

Expected before the fix: `alembic upgrade head` fails with PostgreSQL reporting
that `randomblob(integer)` does not exist. Use only the disposable
`butler_test` database.

- [ ] **Step 3: Make the original migration dialect-aware**

Replace the backfill section of
`alembic/versions/add_trace_id_20260613.py` with:

```python
def _backfill_task_trace_ids() -> None:
    """按数据库方言回填任务追踪标识；无参数，无返回值"""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            UPDATE research_tasks
            SET trace_id = substr(md5(id), 1, 16)
            WHERE trace_id IS NULL OR trace_id = ''
            """
        )
        return
    op.execute(
        """
        UPDATE research_tasks
        SET trace_id = lower(substr(hex(randomblob(16)), 1, 16))
        WHERE trace_id IS NULL OR trace_id = ''
        """
    )


def _backfill_event_trace_ids() -> None:
    """从所属任务回填事件追踪标识；无参数，无返回值"""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            UPDATE research_events AS event
            SET trace_id = task.trace_id
            FROM research_tasks AS task
            WHERE event.task_id = task.id
              AND (event.trace_id IS NULL OR event.trace_id = '')
            """
        )
        return
    op.execute(
        """
        UPDATE research_events
        SET trace_id = (
            SELECT research_tasks.trace_id
            FROM research_tasks
            WHERE research_tasks.id = research_events.task_id
        )
        WHERE trace_id IS NULL OR trace_id = ''
        """
    )
```

Call `_backfill_task_trace_ids()` after adding the task column and
`_backfill_event_trace_ids()` after adding the event column. Remove the old
unconditional SQL and do not backfill event rows with an empty string.

- [ ] **Step 4: Add a follow-up repair migration**

Create `alembic/versions/repair_trace_id_20260614.py`:

```python
"""
修复历史 trace_id 回填。

Workflow:
1. 修复已应用旧迁移但任务 trace_id 为空的数据库。
2. 从研究任务同步事件 trace_id。
3. 保持 schema 不变，仅修复数据。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "repair_trace_id_20260614"
down_revision: Union[str, Sequence[str], None] = "add_trace_id_20260613"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """修复任务和事件追踪标识；无参数，无返回值"""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            UPDATE research_tasks
            SET trace_id = substr(md5(id), 1, 16)
            WHERE trace_id IS NULL OR trace_id = ''
            """
        )
        op.execute(
            """
            UPDATE research_events AS event
            SET trace_id = task.trace_id
            FROM research_tasks AS task
            WHERE event.task_id = task.id
              AND (event.trace_id IS NULL OR event.trace_id = '')
            """
        )
        return
    op.execute(
        """
        UPDATE research_tasks
        SET trace_id = lower(substr(hex(randomblob(16)), 1, 16))
        WHERE trace_id IS NULL OR trace_id = ''
        """
    )
    op.execute(
        """
        UPDATE research_events
        SET trace_id = (
            SELECT research_tasks.trace_id
            FROM research_tasks
            WHERE research_tasks.id = research_events.task_id
        )
        WHERE trace_id IS NULL OR trace_id = ''
        """
    )


def downgrade() -> None:
    """数据修复迁移无需回滚；无参数，无返回值"""
    return None
```

- [ ] **Step 5: Verify migrations on a clean PostgreSQL schema**

Use the disposable test database only:

```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run alembic downgrade base

DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run alembic upgrade head

TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
REDIS_URL='redis://127.0.0.1:6379/15' \
DEEPSEEK_API_KEY=test \
uv run pytest tests/integration -q
```

Expected: `13 passed`; no `randomblob` or missing `trace_id` error.

Also verify the source branch without changing test files:

```bash
rg -n 'if dialect == "postgresql"|md5\\(id\\)' \
  alembic/versions/add_trace_id_20260613.py \
  alembic/versions/repair_trace_id_20260614.py
```

Expected: both migrations contain a PostgreSQL branch and deterministic
`md5(id)` task backfill.

- [ ] **Step 6: Record the incident**

Add to `docs/agent/troubleshooting.md`:

- symptom: PostgreSQL reports `function randomblob(integer) does not exist`;
- check: run `alembic upgrade head` against PostgreSQL, not only SQLite;
- cause: dialect-specific migration SQL;
- fix: branch on `op.get_bind().dialect.name`;
- regression command: the integration suite above.

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/add_trace_id_20260613.py \
  alembic/versions/repair_trace_id_20260614.py \
  tests/integration/test_postgres_schema.py \
  docs/agent/troubleshooting.md
git commit -m "fix: make trace migrations postgres compatible"
```

## Task 2: Make Evaluation Provenance Explicit

**Files:**

- Modify: `src/research/evaluation/schemas.py`
- Modify: `src/cli/evaluate_research.py`
- Modify: `tests/test_research_evaluation.py`
- Create: `artifacts/evaluation/2026-06-interview-baseline.json`

- [ ] **Step 1: Add a failing provenance test**

Extend `test_cli_output_format()`:

```python
    assert data["provenance"] == {
        "evaluation_mode": "offline_fixture",
        "artifact_source": str(fixtures),
        "external_calls": False,
        "pipeline_execution": False,
        "latency_source": "fixture_input",
        "cost_source": "fixture_input",
    }
```

Add a model test:

```python
def test_evaluation_provenance_is_explicit():
    """验证离线评测不会被误认为真实模型运行"""
    provenance = EvaluationProvenance(
        artifact_source="tests/fixtures/research_eval_cases.json"
    )
    assert provenance.evaluation_mode == "offline_fixture"
    assert provenance.external_calls is False
    assert provenance.pipeline_execution is False
```

Import `EvaluationProvenance`.

- [ ] **Step 2: Run the tests and confirm failure**

```bash
uv run pytest \
  tests/test_research_evaluation.py::test_evaluation_provenance_is_explicit \
  tests/test_research_evaluation.py::test_cli_output_format \
  -q
```

Expected: fail because `EvaluationProvenance` and `provenance` output do not
exist.

- [ ] **Step 3: Add the provenance schema**

Add to `src/research/evaluation/schemas.py`:

```python
class EvaluationProvenance(BaseModel):
    """离线评测来源说明，防止把 fixture 数据描述为在线实测"""

    evaluation_mode: str = "offline_fixture"
    artifact_source: str
    external_calls: bool = False
    pipeline_execution: bool = False
    latency_source: str = "fixture_input"
    cost_source: str = "fixture_input"
```

- [ ] **Step 4: Emit provenance from the CLI**

Update `src/cli/evaluate_research.py`:

```python
from src.research.evaluation.schemas import EvaluationProvenance
```

After parsing arguments:

```python
    cases_path = Path(args.cases)
```

Use `cases_path` for the runner and add:

```python
        "provenance": EvaluationProvenance(
            artifact_source=str(cases_path)
        ).model_dump(),
```

The CLI remains offline. Do not call `LLMClient`, external providers, or the
research worker.

- [ ] **Step 5: Run evaluation tests**

```bash
uv run pytest tests/test_research_evaluation.py -q
```

Expected: all evaluation tests pass.

- [ ] **Step 6: Generate the standard evaluation artifact**

```bash
uv run butler-evaluate-research \
  --cases tests/fixtures/research_eval_cases.json \
  --offline \
  --output artifacts/evaluation/2026-06-interview-baseline.json

uv run python -m json.tool \
  artifacts/evaluation/2026-06-interview-baseline.json >/dev/null
```

Expected:

- `summary.case_count == 24`;
- `provenance.evaluation_mode == "offline_fixture"`;
- `provenance.external_calls == false`;
- metrics remain non-constant.

- [ ] **Step 7: Commit**

```bash
git add src/research/evaluation/schemas.py \
  src/cli/evaluate_research.py \
  tests/test_research_evaluation.py \
  artifacts/evaluation/2026-06-interview-baseline.json
git commit -m "fix: label offline evaluation provenance"
```

## Task 3: Replace the Sleep-Only Benchmark with a PostgreSQL Harness

**Files:**

- Modify: `src/research/benchmark.py`
- Modify: `src/cli/benchmark_research.py`
- Modify: `tests/test_research_benchmark.py`
- Create: `tests/integration/test_research_benchmark_postgres.py`
- Create: `artifacts/benchmarks/.gitkeep`
- Create: `artifacts/benchmarks/2026-06-interview-baseline.json`

- [ ] **Step 1: Write a database-usage regression test**

Create `tests/integration/test_research_benchmark_postgres.py`:

```python
"""
PostgreSQL 控制基准测试。

Workflow:
1. 使用真实 PostgreSQL 创建 benchmark 任务和步骤。
2. 多个异步 worker 通过 SKIP LOCKED 认领步骤。
3. 验证输出指标来自真实数据库状态转换。
"""
import os

import pytest
from sqlalchemy import func, select

from src.models.research_execution import ResearchStep
from src.research.benchmark import BenchmarkConfig, run_full_benchmark


@pytest.mark.asyncio
async def test_postgres_benchmark_persists_and_completes_steps(
    postgres_engine,
    postgres_schema,
):
    """验证 benchmark 真实写入并完成 PostgreSQL 步骤"""
    config = BenchmarkConfig(
        database_url=os.environ["TEST_DATABASE_URL"],
        worker_counts=[1],
        task_count=3,
        timeout_seconds=1,
        seed=7,
    )

    results = await run_full_benchmark(config, scenarios=["normal"])

    assert len(results) == 1
    assert results[0].benchmark_kind == "postgresql_controlled_harness"
    assert results[0].database_dialect == "postgresql"
    assert results[0].success_count == 3
    assert results[0].duplicate_claim_count == 0

    async with postgres_engine.connect() as connection:
        completed = await connection.scalar(
            select(func.count())
            .select_from(ResearchStep)
            .where(
                ResearchStep.id.like("BENCH-%"),
                ResearchStep.status == "completed",
            )
        )
    assert completed >= 3
```

- [ ] **Step 2: Add a failing invalid-database test**

Add to `tests/test_research_benchmark.py`:

```python
@pytest.mark.asyncio
async def test_benchmark_rejects_unreachable_postgres():
    """验证 benchmark 不会忽略 database_url"""
    config = BenchmarkConfig(
        database_url=(
            "postgresql+asyncpg://invalid:invalid@127.0.0.1:1/missing"
        ),
        worker_counts=[1],
        task_count=1,
        timeout_seconds=1,
        seed=7,
    )
    with pytest.raises(Exception):
        await run_full_benchmark(config, scenarios=["normal"])
```

- [ ] **Step 3: Run both tests and confirm failure**

```bash
uv run pytest \
  tests/test_research_benchmark.py::test_benchmark_rejects_unreachable_postgres \
  -q

TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run pytest \
  tests/integration/test_research_benchmark_postgres.py \
  -q
```

Expected: fail because the current runner never creates an engine or database
rows.

- [ ] **Step 4: Define truthful benchmark models**

Replace unused `failure_rate` and `fake_latency_range` fields in
`BenchmarkConfig`, and make the database URL required:

```python
    database_url: str
    seed: int = 7
    normal_latency_ms: int = 25
    timeout_latency_ms: int = 100
```

Add to `BenchmarkResult`:

```python
    benchmark_kind: str = "postgresql_controlled_harness"
    database_dialect: str = "postgresql"
    external_dependencies: str = "fake"
    retry_count: int = 0
    duplicate_claim_count: int = 0
```

Keep the existing latency and throughput fields so downstream JSON remains
easy to compare.

Update the unit tests to match the new defaults. Replace the old
`run_benchmark_scenario()` and database-free `run_full_benchmark()` tests with
unit tests for `_percentile()` and `_run_controlled_scenario()`. Keep
`run_full_benchmark()` coverage in the PostgreSQL integration test and the
unreachable-database regression test.

Use a non-routable PostgreSQL URL whenever a model-only test needs to construct
the config without connecting:

```python
config = BenchmarkConfig(
    database_url=(
        "postgresql+asyncpg://invalid:invalid@127.0.0.1:1/missing"
    )
)
```

- [ ] **Step 5: Implement PostgreSQL-backed seeding**

In `src/research/benchmark.py`, import:

```python
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
```

Add:

```python
async def _seed_benchmark_steps(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: str,
    task_count: int,
) -> str:
    """创建一组可并发认领的基准步骤并返回任务 ID"""
    workspace_id = f"bench-{run_id}"
    task_id = f"BENCH-{run_id}"
    async with session_factory() as db:
        db.add(
            Workspace(
                id=workspace_id,
                name=f"Benchmark {run_id}",
                status="active",
            )
        )
        db.add(
            ResearchTask(
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
            )
        )
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
            db.add(
                ResearchStep(
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
                )
            )
        await db.commit()
    return task_id
```

- [ ] **Step 6: Implement worker execution through real claims**

Use deterministic delays:

```python
async def _run_controlled_scenario(
    scenario: str,
    *,
    normal_latency_ms: int,
    timeout_latency_ms: int,
) -> None:
    """执行可复现的外部依赖模拟；参数为场景和延迟，无返回值"""
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
```

Do not use `random`, and remove unused `median`.

Add shared state and a worker that commits each claim before running the fake
provider, then persists the terminal status in a separate transaction:

```python
@dataclass
class _BenchmarkRunState:
    """保存单轮基准结果和重复认领计数"""

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
    """循环认领并完成步骤；参数描述会话、任务和场景，无返回值"""
    step_service = ResearchStepService()
    while True:
        async with session_factory() as db:
            claimed = await step_service.claim_next(
                db,
                owner=worker_id,
                limit=1,
                task_id=task_id,
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
        error: str | None = None
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
                result_ref=(
                    f"benchmark://{task_id}/{step_id}"
                    if error is None
                    else None
                ),
                error=error,
            )
            await db.commit()

        state.results.append(
            BenchmarkTaskResult(
                task_id=step_id,
                worker_count=worker_count,
                scenario=scenario,
                success=error is None,
                latency_s=elapsed,
                error=error,
            )
        )
```

- [ ] **Step 7: Make `run_full_benchmark()` own the engine lifecycle**

Add a scenario runner that seeds rows, starts exactly `worker_count` workers,
and verifies that every seeded work item reached a terminal database state:

```python
async def _run_postgres_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    config: BenchmarkConfig,
    scenario: str,
    worker_count: int,
) -> BenchmarkResult:
    """运行单个 PostgreSQL 控制场景并返回汇总结果"""
    run_id = uuid4().hex[:12]
    task_id = await _seed_benchmark_steps(
        session_factory,
        run_id=run_id,
        task_count=config.task_count,
    )
    state = _BenchmarkRunState()
    started = time.monotonic()
    await asyncio.gather(
        *[
            _run_benchmark_worker(
                session_factory,
                task_id=task_id,
                worker_id=f"{run_id}-worker-{index}",
                worker_count=worker_count,
                scenario=scenario,
                config=config,
                state=state,
            )
            for index in range(worker_count)
        ]
    )
    total_duration = time.monotonic() - started

    async with session_factory() as db:
        terminal_count = await db.scalar(
            select(func.count())
            .select_from(ResearchStep)
            .where(
                ResearchStep.task_id == task_id,
                ResearchStep.status.in_(
                    [
                        ResearchStepStatus.COMPLETED.value,
                        ResearchStepStatus.FAILED.value,
                    ]
                ),
            )
        )
    if terminal_count != config.task_count:
        raise RuntimeError(
            f"expected {config.task_count} terminal steps, "
            f"got {terminal_count}"
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
        mean_latency_s=(
            sum(latencies) / len(latencies) if latencies else 0.0
        ),
        throughput_tasks_per_sec=(
            len(results) / total_duration if total_duration else 0.0
        ),
        retry_count=0,
        duplicate_claim_count=state.duplicate_claim_count,
        results=results,
    )
```

Replace `run_full_benchmark()` with explicit engine ownership:

```python
async def run_full_benchmark(
    config: BenchmarkConfig,
    scenarios: list[str] | None = None,
) -> list[BenchmarkResult]:
    """运行 PostgreSQL 控制基准；参数为配置和场景，返回汇总列表"""
    selected = scenarios or [
        "normal",
        "timeout",
        "execution_error",
        "rate_limited",
    ]
    engine = create_async_engine(config.database_url, pool_pre_ping=True)
    try:
        if engine.dialect.name != "postgresql":
            raise ValueError(
                "controlled benchmark requires postgresql+asyncpg"
            )
        async with engine.connect():
            pass
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        results: list[BenchmarkResult] = []
        for scenario in selected:
            for worker_count in config.worker_counts:
                results.append(
                    await _run_postgres_scenario(
                        session_factory,
                        config=config,
                        scenario=scenario,
                        worker_count=worker_count,
                    )
                )
        return results
    finally:
        await engine.dispose()
```

The harness measures PostgreSQL task/step persistence and concurrent claims.
It does not call DeepSeek, web search, Redis, Taskiq workers, or WeChat.

- [ ] **Step 8: Export provenance from the benchmark CLI**

Change `--database-url` in `src/cli/benchmark_research.py` to
`required=True`, remove the in-memory SQLite default, and update its help text
to state that the command requires a disposable PostgreSQL database.

Add these fields to each JSON result:

```python
                "benchmark_kind": r.benchmark_kind,
                "database_dialect": r.database_dialect,
                "external_dependencies": r.external_dependencies,
                "retry_count": r.retry_count,
                "duplicate_claim_count": r.duplicate_claim_count,
```

Add top-level:

```python
        "provenance": {
            "benchmark_kind": "postgresql_controlled_harness",
            "external_dependencies": "fake",
            "taskiq_transport": False,
            "production_traffic": False,
        },
```

- [ ] **Step 9: Run benchmark tests**

```bash
uv run pytest tests/test_research_benchmark.py -q

TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run pytest \
  tests/integration/test_research_benchmark_postgres.py \
  -q
```

Expected: all pass, including rejection of an unreachable database.

- [ ] **Step 10: Generate the standard benchmark artifact**

```bash
uv run butler-benchmark-research \
  --database-url 'postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  --worker-counts 1,3,5 \
  --task-count 12 \
  --output artifacts/benchmarks/2026-06-interview-baseline.json

uv run python -m json.tool \
  artifacts/benchmarks/2026-06-interview-baseline.json >/dev/null
```

Expected:

- `config.worker_counts == [1, 3, 5]`;
- `config.task_count == 12`;
- `provenance.benchmark_kind == "postgresql_controlled_harness"`;
- every result has `database_dialect == "postgresql"`;
- every result has `duplicate_claim_count == 0`.

- [ ] **Step 11: Commit**

```bash
git add src/research/benchmark.py \
  src/cli/benchmark_research.py \
  tests/test_research_benchmark.py \
  tests/integration/test_research_benchmark_postgres.py \
  artifacts/benchmarks/.gitkeep \
  artifacts/benchmarks/2026-06-interview-baseline.json
git commit -m "fix: benchmark real postgres step execution"
```

## Task 4: Correct Interview and Project Documentation

**Files:**

- Modify: `docs/interview/project-brief.md`
- Modify: `docs/interview/architecture.md`
- Modify: `docs/interview/demo-script.md`
- Modify: `docs/interview/metrics.md`
- Modify: `docs/interview/star-stories.md`
- Modify: `docs/interview/question-bank.md`
- Modify: `PROJECT_STUDY_GUIDE.md`
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/upgrade-roadmap.md`
- Modify: `docs/operations/research-runbook.md`

- [ ] **Step 1: Add a documentation truth-check script command**

Use this command throughout the task:

```bash
rg -n \
  "real DeepSeek|runs through the full pipeline|registration time|span_id|status='pending'|production-proven|SQLite benchmark|1/2 workers|artifacts/evaluation/results.json|artifacts/evaluation/benchmark_results.json" \
  docs/interview PROJECT_STUDY_GUIDE.md docs/agent \
  docs/operations/research-runbook.md
```

The task is complete only when remaining matches are explicit historical or
limitation statements.

- [ ] **Step 2: Correct capability and architecture statements**

Update `docs/interview/project-brief.md` and
`docs/interview/architecture.md`:

- evaluation status:
  `24-case offline fixture evaluation; no external calls`;
- benchmark status:
  `PostgreSQL controlled harness, 1/3/5 workers, fake external dependencies`;
- tool permission wording:
  registered tools are checked by `PermissionEngine` at execution time;
- step claim wording:
  workers select `ready` rows with `FOR UPDATE SKIP LOCKED`, then persist
  `running`, owner, attempt count, and lease;
- remove any statement that registration itself denies a tool;
- remove any assertion that Redis queue loss is automatically repaired unless
  a specific implemented reconciliation path is cited.

- [ ] **Step 3: Rewrite metrics with provenance**

Update `docs/interview/metrics.md` to reference only:

- `artifacts/evaluation/2026-06-interview-baseline.json`;
- `artifacts/benchmarks/2026-06-interview-baseline.json`.

Use these labels:

```text
Quality metrics: calculated from versioned fixture artifacts.
Latency/cost in the evaluation file: fixture metadata, not measured API usage.
Benchmark: real PostgreSQL persistence and claim concurrency with fake external dependencies.
Not measured: production QPS, DeepSeek latency, Taskiq transport throughput, factual accuracy.
```

Generate tables from the new artifacts. Do not manually preserve old 1/2
worker values.

- [ ] **Step 4: Correct STAR stories and question bank**

In `docs/interview/star-stories.md`, replace “executes the full pipeline” with
“calculates deterministic metrics from versioned fixture artifacts”.

In `docs/interview/question-bank.md`, correct at least these answers:

- Q6, Q29, Q41, Q43: offline fixture evaluator, no DeepSeek call;
- Q7: permission decision occurs when `ResearchToolRegistry.execute()` runs;
- Q9, Q53, Q54, Q55: use actual `ready`/`running` states and
  `SELECT ... FOR UPDATE SKIP LOCKED`; dependency unblocking is handled by
  `ResearchStepService._unblock_dependents()`;
- Q58 and Q78: only `trace_id` exists; no `span_id` or full-trace status API;
- Q56: describe Taskiq as the selected async framework, not
  “production-proven” without project evidence;
- Q79: use the new 1/3/5 PostgreSQL controlled-harness artifact.

Every corrected answer must cite the actual file or method name.

- [ ] **Step 5: Make the demo script executable**

Update `docs/interview/demo-script.md`:

- replace `cd READINESS_REPO` with the actual repository-root instruction;
- set `DATABASE_URL` on the Alembic command;
- use existing test names:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_pipeline.py::test_full_research_pipeline_reaches_delivery \
  -q
```

- do not print expected nonexistent test names;
- show the standard evaluation and benchmark artifact paths;
- describe the evaluation as offline fixture scoring;
- describe the benchmark as PostgreSQL controlled-harness evidence;
- include a fallback that reads committed artifacts without claiming a live
  model or live WeChat demonstration.

- [ ] **Step 6: Correct project memory and study guide**

Update:

- `PROJECT_STUDY_GUIDE.md`: PostgreSQL is authoritative in production;
  SQLite is a development fallback, not the universal task-state store;
- `docs/agent/active-context.md`: replace 1/2-worker benchmark with the new
  controlled-harness status and remove the duplicate Phase 6 bullet;
- `docs/agent/upgrade-roadmap.md`: CI is complete only after the corrected
  GitHub Actions run is green; live DeepSeek E2E remains future work;
- `docs/operations/research-runbook.md`: add exact migration, evaluation, and
  controlled benchmark commands plus provenance limitations.

- [ ] **Step 7: Run the documentation truth check**

```bash
if rg -n \
  "real DeepSeek|runs through the full pipeline|registration time|span_id|status='pending'|production-proven|SQLite benchmark|1/2 workers|artifacts/evaluation/results.json|artifacts/evaluation/benchmark_results.json" \
  docs/interview PROJECT_STUDY_GUIDE.md docs/agent \
  docs/operations/research-runbook.md; then
  exit 1
fi

git diff --check
cmp -s CLAUDE.md AGENTS.md
```

Expected:

- no unsupported current-capability claim;
- `git diff --check` exits `0`;
- agent docs comparison exits `0`.

- [ ] **Step 8: Commit**

```bash
git add docs/interview PROJECT_STUDY_GUIDE.md \
  docs/agent/active-context.md \
  docs/agent/upgrade-roadmap.md \
  docs/operations/research-runbook.md
git commit -m "docs: align interview evidence with implementation"
```

## Task 5: Reopen and Pass the Final Acceptance Gate

**Files:**

- Modify: `docs/superpowers/plans/2026-06-13-interview-readiness-remediation-master.md`
- Modify: `docs/agent/troubleshooting.md`
- Verify: all corrective files and artifacts

- [ ] **Step 1: Run the complete unit suite**

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: no failures.

- [ ] **Step 2: Recreate the PostgreSQL schema and run integration tests**

```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run alembic downgrade base

DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run alembic upgrade head

TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
REDIS_URL='redis://127.0.0.1:6379/15' \
DEEPSEEK_API_KEY=test \
uv run pytest tests/integration -q
```

Expected: all integration tests pass.

- [ ] **Step 3: Regenerate both standard artifacts**

```bash
uv run butler-evaluate-research \
  --cases tests/fixtures/research_eval_cases.json \
  --offline \
  --output artifacts/evaluation/2026-06-interview-baseline.json

uv run butler-benchmark-research \
  --database-url 'postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  --worker-counts 1,3,5 \
  --task-count 12 \
  --output artifacts/benchmarks/2026-06-interview-baseline.json
```

- [ ] **Step 4: Validate artifact semantics**

```bash
uv run python - <<'PY'
import json
from pathlib import Path

evaluation = json.loads(
    Path(
        "artifacts/evaluation/2026-06-interview-baseline.json"
    ).read_text()
)
benchmark = json.loads(
    Path(
        "artifacts/benchmarks/2026-06-interview-baseline.json"
    ).read_text()
)

assert evaluation["summary"]["case_count"] == 24
assert evaluation["provenance"]["evaluation_mode"] == "offline_fixture"
assert evaluation["provenance"]["external_calls"] is False
assert benchmark["config"]["worker_counts"] == [1, 3, 5]
assert benchmark["config"]["task_count"] == 12
assert benchmark["provenance"]["benchmark_kind"] == (
    "postgresql_controlled_harness"
)
assert all(
    result["database_dialect"] == "postgresql"
    for result in benchmark["results"]
)
assert all(
    result["duplicate_claim_count"] == 0
    for result in benchmark["results"]
)
print("artifact_semantics=ok")
PY
```

Expected: `artifact_semantics=ok`.

- [ ] **Step 5: Execute every demo command**

Run `docs/interview/demo-script.md` from top to bottom in a clean shell. Record
the actual duration in the document. No command may rely on an undocumented
manual database edit.

- [ ] **Step 6: Run final static checks**

```bash
uv run python -m compileall -q src tests
git diff --check
cmp -s CLAUDE.md AGENTS.md
if rg -n "TODO|TBD|FIXME" \
  README.md README.en.md PROJECT_STUDY_GUIDE.md \
  docs/interview docs/agent docs/operations/research-runbook.md; then
  exit 1
fi
```

Expected: all commands exit `0`; the guarded `rg` check finds no matches.

- [ ] **Step 7: Confirm GitHub Actions**

Push the implementation branch and wait for both jobs in
`.github/workflows/test.yml`.

Expected:

- `unit`: success;
- `integration`: success;
- Alembic upgrade step: success.

Do not declare Gate 4 complete from a local run alone.

- [ ] **Step 8: Update master-plan status**

Add this table near the top of
`docs/superpowers/plans/2026-06-13-interview-readiness-remediation-master.md`:

```markdown
## Execution Status

| Phase | Status | Evidence |
|---|---|---|
| Week 1 | Complete | Unit pipeline and provider tests |
| Week 2 | Complete after correction | PostgreSQL/Redis integration suite and green CI |
| Week 3 | Complete after correction | Explicit offline evaluation provenance and PostgreSQL controlled benchmark |
| Week 4 | Complete after re-audit | Executable demo, corrected interview docs, standard artifacts |
| Corrective plan | Complete | `2026-06-14-interview-readiness-corrective-plan.md` |
```

Do not add this table until Steps 1-7 pass.

- [ ] **Step 9: Commit final acceptance evidence**

```bash
git add docs/superpowers/plans/2026-06-13-interview-readiness-remediation-master.md \
  docs/agent/troubleshooting.md \
  docs/interview \
  artifacts/evaluation/2026-06-interview-baseline.json \
  artifacts/benchmarks/2026-06-interview-baseline.json
git commit -m "docs: complete corrected interview readiness audit"
```

The final commit must contain actual changed evidence or status files. Do not
use an empty commit as proof of verification.

- [ ] **Step 10: Push the final acceptance commit and recheck CI**

Push the commit from Step 9 and wait for the new workflow run. Both `unit` and
`integration` must be green for that exact commit SHA. If either job fails,
restore the master-plan status to pending before making further fixes.

## Final Acceptance Checklist

- [ ] PostgreSQL can migrate from base to head.
- [ ] Unit suite passes.
- [ ] PostgreSQL/Redis integration suite passes.
- [ ] GitHub Actions unit and integration jobs pass.
- [ ] Evaluation artifact explicitly says it is offline and fixture-derived.
- [ ] Benchmark rejects an unreachable PostgreSQL URL.
- [ ] Benchmark uses real PostgreSQL task/plan/step records.
- [ ] Benchmark artifact covers 1/3/5 workers and 12 tasks.
- [ ] Benchmark artifact states that external dependencies are fake.
- [ ] Interview documents contain no claim of live DeepSeek evaluation.
- [ ] Interview documents describe actual ready-step claim semantics.
- [ ] Interview documents describe execution-time permission checks.
- [ ] Interview documents contain no unsupported `span_id` or trace-query API.
- [ ] Demo commands execute exactly as written.
- [ ] Standard evaluation and benchmark artifacts exist and validate.
- [ ] Master plan status is updated only after the corrected CI run succeeds.
