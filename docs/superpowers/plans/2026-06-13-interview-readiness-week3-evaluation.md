# Week 3 Evaluation and Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed scores and unconnected trace fields with reproducible quality, latency, cost, concurrency, and failure evidence.

**Architecture:** Evaluate deterministic report artifacts against versioned case expectations, persist a trace ID on authoritative task/event records, record stage timings through one small recorder, and run a controlled PostgreSQL benchmark with fake external dependencies.

**Tech Stack:** Pydantic v2, SQLAlchemy async, Alembic, PostgreSQL, JSON fixtures, pytest, project CLI entry points

---

## File Map

**Modify**

- `src/models/research.py`
- `src/models/research_execution.py`
- `src/research/evaluation/schemas.py`
- `src/research/evaluation/runner.py`
- `src/research/observability.py`
- `src/research/events.py`
- `src/research/tasks.py`
- `src/cli/evaluate_research.py`
- `pyproject.toml`
- `tests/fixtures/research_eval_cases.json`
- `tests/test_research_evaluation.py`
- `tests/test_research_observability.py`

**Create**

- `alembic/versions/<revision>_add_research_trace_ids.py`
- `src/research/benchmark.py`
- `src/cli/benchmark_research.py`
- `tests/test_research_benchmark.py`
- `tests/integration/test_research_trace.py`
- `artifacts/evaluation/.gitkeep`
- `artifacts/benchmarks/.gitkeep`

## Task 1: Define Deterministic Evaluation Inputs

- [ ] **Step 1: Write schema tests**

Extend `tests/test_research_evaluation.py`:

```python
def test_evaluation_case_and_artifact_validate():
    case = EvaluationCase(
        id="comparison-001",
        question="Compare Taskiq and Celery",
        category="comparison",
        required_claim_topics=["async", "delivery"],
        required_source_types=["knowledge", "web"],
        forbidden_claims=["exactly-once"],
        max_unsupported_material_claim_rate=0.0,
        max_cost_microunits=500_000,
    )
    artifact = EvaluationArtifact(
        claims=[
            EvaluationClaim(
                text="Taskiq is async-native.",
                material=True,
                validation_status="supported",
                evidence_ids=[1],
            )
        ],
        evidence=[
            EvaluationEvidence(id=1, source_type="web"),
        ],
        latency_ms=1200,
        estimated_cost_microunits=1200,
    )
    assert case.id == "comparison-001"
    assert artifact.claims[0].evidence_ids == [1]
```

- [ ] **Step 2: Implement schemas**

Define in `src/research/evaluation/schemas.py`:

- `EvaluationCase`;
- `EvaluationClaim`;
- `EvaluationEvidence`;
- `EvaluationArtifact`;
- `EvaluationResult`;
- `EvaluationSummary`.

Constrain every ratio to `0.0 <= value <= 1.0`.

- [ ] **Step 3: Run schema tests**

```bash
uv run pytest tests/test_research_evaluation.py -q
```

Expected: schema tests pass while metric tests still fail.

- [ ] **Step 4: Commit**

```bash
git add src/research/evaluation/schemas.py tests/test_research_evaluation.py
git commit -m "feat: define research evaluation artifacts"
```

## Task 2: Implement Metric Formulas

- [ ] **Step 1: Write exact metric tests**

Add tests for:

```python
assert result.claim_topic_coverage == 0.5
assert result.citation_validity == 0.5
assert result.unsupported_material_claim_rate == 0.5
assert result.required_source_coverage == 0.5
assert result.within_cost_budget is True
```

Use two required topics, two material claims, and two required source types so
the expected fractions are unambiguous.

- [ ] **Step 2: Implement evaluator helpers**

In `src/research/evaluation/runner.py`, add:

```python
def _normalize(text: str) -> str:
    """归一化评测文本；参数为原文，返回大小写和空白统一后的文本"""
    return " ".join(text.casefold().split())


def _coverage(required: list[str], corpus: str) -> float:
    """计算要求项覆盖率；参数为要求项和语料，返回零到一的比例"""
    if not required:
        return 1.0
    normalized = _normalize(corpus)
    hits = sum(_normalize(item) in normalized for item in required)
    return hits / len(required)
```

Define:

- topic coverage = required topics found in supported claim text / required
  topics;
- citation validity = material claims with `supported` status and at least one
  existing evidence ID / material claims;
- unsupported rate = unsupported material claims / material claims;
- source coverage = required source types present / required source types;
- forbidden-claim hit count from all claim text;
- cost-budget flag from case maximum.

- [ ] **Step 3: Replace fixed results**

Change `EvaluationRunner.run_offline()` to read cases containing an `artifact`
object and calculate each result. It must raise a validation error when an
artifact is missing instead of assigning perfect scores.

- [ ] **Step 4: Add aggregate summary**

Implement mean metrics and totals:

```python
EvaluationSummary(
    case_count=len(results),
    mean_topic_coverage=...,
    mean_citation_validity=...,
    mean_unsupported_material_claim_rate=...,
    mean_required_source_coverage=...,
    total_estimated_cost_microunits=...,
    mean_latency_ms=...,
)
```

- [ ] **Step 5: Run metric tests**

```bash
uv run pytest tests/test_research_evaluation.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/research/evaluation/runner.py \
  src/research/evaluation/schemas.py tests/test_research_evaluation.py
git commit -m "feat: calculate deterministic research quality metrics"
```

## Task 3: Build the Evaluation Dataset

- [ ] **Step 1: Expand fixtures to at least 20 cases**

Update `tests/fixtures/research_eval_cases.json` with these IDs and categories:

1. `comparison-001` Taskiq versus Celery
2. `comparison-002` LangGraph versus a linear chain
3. `comparison-003` PostgreSQL versus SQLite for workers
4. `factual-001` URL callback idempotency
5. `factual-002` Redis Stream delivery semantics
6. `factual-003` Chroma metadata filtering
7. `factual-004` Open-Meteo key requirements
8. `internal-001` project research command
9. `internal-002` project workspace isolation
10. `internal-003` project report delivery path
11. `conflict-001` conflicting queue guarantees
12. `conflict-002` conflicting RAG source dates
13. `insufficient-001` no evidence for exact throughput
14. `insufficient-002` no evidence for production user count
15. `security-001` private-network fetch claim
16. `security-002` source prompt-injection claim
17. `reliability-001` expired step lease
18. `reliability-002` provider circuit opening
19. `cost-001` soft budget narrowing
20. `cost-002` hard budget termination
21. `citation-001` unsupported material claim
22. `citation-002` citation points to wrong evidence
23. `scope-001` user-private knowledge boundary
24. `scope-002` cross-workspace research lookup

Each case must include an artifact that produces a deliberate mix of passing
and failing metrics. Do not make every case perfect.

- [ ] **Step 2: Add dataset validation test**

```python
def test_evaluation_dataset_has_required_coverage():
    cases = load_cases(FIXTURE)
    assert len(cases) >= 20
    assert {case.category for case in cases} >= {
        "comparison",
        "factual",
        "internal",
        "conflict",
        "insufficient",
        "security",
        "reliability",
        "cost",
        "citation",
        "scope",
    }
```

- [ ] **Step 3: Run dataset tests**

```bash
uv run pytest tests/test_research_evaluation.py -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/research_eval_cases.json \
  tests/test_research_evaluation.py
git commit -m "test: add versioned research evaluation set"
```

## Task 4: Export Evaluation Results

- [ ] **Step 1: Add CLI output test**

Test that `run()` writes:

```json
{
  "generated_at": "...",
  "summary": {},
  "results": []
}
```

- [ ] **Step 2: Extend CLI arguments**

Update `src/cli/evaluate_research.py` to support:

```text
--cases PATH
--output PATH
```

Create parent directories, write UTF-8 pretty JSON, and print the output path
plus summary.

- [ ] **Step 3: Run evaluator**

```bash
uv run butler-evaluate-research \
  --cases tests/fixtures/research_eval_cases.json \
  --output artifacts/evaluation/latest.json
```

Expected: the file contains at least 20 results and non-identical metric rows.

- [ ] **Step 4: Commit**

```bash
git add src/cli/evaluate_research.py artifacts/evaluation/.gitkeep \
  tests/test_research_evaluation.py
git commit -m "feat: export research evaluation results"
```

## Task 5: Persist and Propagate Trace IDs

- [ ] **Step 1: Write model tests**

Add assertions that `ResearchTask.trace_id` and `ResearchEvent.trace_id` are
non-null and indexed. Usage, review, step, and delivery assertions must prove
they can be joined to the traced task through existing task/step foreign keys.

- [ ] **Step 2: Add model fields**

Add:

```python
trace_id: Mapped[str] = mapped_column(
    String(32),
    nullable=False,
    index=True,
)
```

to `ResearchTask` and `ResearchEvent`.

Generate it in `ResearchTaskService.create_task()`:

```python
trace_id=uuid.uuid4().hex[:16],
```

- [ ] **Step 3: Add Alembic migration**

Create a migration that:

1. adds nullable `trace_id` columns;
2. backfills existing tasks with deterministic values derived from task IDs;
3. backfills events by joining their task;
4. makes both columns non-null;
5. creates indexes.

- [ ] **Step 4: Update EventWriter**

Load or accept the task trace ID and persist it in every event. Do not place
the trace ID only inside JSON payload.

- [ ] **Step 5: Run migration tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_models.py \
  tests/test_research_events.py \
  tests/test_research_observability.py -q

TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run pytest tests/integration/test_postgres_schema.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/models/research.py src/models/research_execution.py \
  src/research/service.py src/research/events.py alembic/versions \
  tests/test_research_models.py tests/test_research_events.py \
  tests/test_research_observability.py
git commit -m "feat: persist research trace identifiers"
```

## Task 6: Record Stage Measurements

- [ ] **Step 1: Write recorder tests**

Extend `tests/test_research_observability.py` to verify:

- `stage.started` and `stage.completed` events share a trace ID;
- completed payload includes `elapsed_ms` and `outcome`;
- a failed stage includes `failure_category`;
- usage records include provider, model, tokens, cost, and latency.

- [ ] **Step 2: Implement StageRecorder**

In `src/research/observability.py`, add an async context manager:

```python
class StageRecorder:
    """记录研究阶段事件、耗时和失败分类"""

    @asynccontextmanager
    async def measure(
        self,
        db,
        *,
        task,
        stage: str,
        step_id: str | None = None,
        attempt: int | None = None,
    ):
        started = time.perf_counter()
        await self._events.append(..., event_type="stage.started", ...)
        try:
            yield
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            await self._events.append(
                ...,
                event_type="stage.failed",
                payload={
                    "stage": stage,
                    "elapsed_ms": elapsed_ms,
                    "failure_category": classify_error(exc).category.value,
                },
            )
            raise
        else:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            await self._events.append(
                ...,
                event_type="stage.completed",
                payload={"stage": stage, "elapsed_ms": elapsed_ms},
            )
```

- [ ] **Step 3: Wrap worker stages**

Use the recorder around:

- planning;
- each tool step;
- synthesis;
- validation;
- delivery.

- [ ] **Step 4: Add trace integration test**

Create `tests/integration/test_research_trace.py`, execute the deterministic
pipeline, and assert one trace ID is present on all stage events while usage,
review, and delivery rows join to that traced task by `task_id`.

- [ ] **Step 5: Run observability tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_observability.py \
  tests/test_research_tasks.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/research/observability.py src/research/tasks.py \
  tests/test_research_observability.py \
  tests/integration/test_research_trace.py
git commit -m "feat: record research stage measurements"
```

## Task 7: Add a Controlled Benchmark

- [ ] **Step 1: Write benchmark aggregation tests**

Create `tests/test_research_benchmark.py` and assert:

```python
assert result.worker_count == 3
assert result.task_count == 12
assert result.success_count + result.failure_count == 12
assert result.duplicate_delivery_count == 0
assert result.p95_latency_ms >= result.p50_latency_ms
```

- [ ] **Step 2: Implement benchmark models and runner**

Create `src/research/benchmark.py` with:

- `BenchmarkConfig`;
- `BenchmarkTaskResult`;
- `BenchmarkResult`;
- percentile calculation;
- async bounded semaphore for worker counts;
- deterministic fake provider latency;
- three configured failure scenarios: provider timeout, expired step lease,
  and queue enqueue failure followed by reconciliation.

The runner must use real PostgreSQL task/step records and fake external
providers. It must not call DeepSeek or the public web.

- [ ] **Step 3: Add CLI**

Create `src/cli/benchmark_research.py` supporting:

```text
--database-url
--worker-counts 1,3,5
--task-count 12
--output artifacts/benchmarks/latest.json
```

Add to `pyproject.toml`:

```toml
butler-benchmark-research = "src.cli.benchmark_research:run"
```

- [ ] **Step 4: Run benchmark tests**

```bash
uv run pytest tests/test_research_benchmark.py -q
```

Expected: all pass.

- [ ] **Step 5: Run the benchmark**

```bash
uv run butler-benchmark-research \
  --database-url 'postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  --worker-counts 1,3,5 \
  --task-count 12 \
  --output artifacts/benchmarks/latest.json
```

Expected: three worker-count result groups, three named failure scenarios, and
zero duplicate delivery in the controlled benchmark.

- [ ] **Step 6: Commit**

```bash
git add src/research/benchmark.py src/cli/benchmark_research.py \
  tests/test_research_benchmark.py pyproject.toml uv.lock \
  artifacts/benchmarks/.gitkeep
git commit -m "feat: benchmark research pipeline concurrency"
```

## Task 8: Freeze Week 3 Evidence

- [ ] **Step 1: Generate evaluation output**

```bash
uv run butler-evaluate-research \
  --cases tests/fixtures/research_eval_cases.json \
  --output artifacts/evaluation/2026-06-interview-baseline.json
```

- [ ] **Step 2: Generate benchmark output**

```bash
uv run butler-benchmark-research \
  --database-url 'postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  --worker-counts 1,3,5 \
  --task-count 12 \
  --output artifacts/benchmarks/2026-06-interview-baseline.json
```

- [ ] **Step 3: Validate artifacts**

```bash
uv run python -m json.tool \
  artifacts/evaluation/2026-06-interview-baseline.json >/dev/null
uv run python -m json.tool \
  artifacts/benchmarks/2026-06-interview-baseline.json >/dev/null
```

Expected: both commands exit `0`.

- [ ] **Step 4: Commit reproducible evidence**

```bash
git add artifacts/evaluation/2026-06-interview-baseline.json \
  artifacts/benchmarks/2026-06-interview-baseline.json
git commit -m "docs: record interview evaluation baseline"
```
