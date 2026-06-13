# Week 2 Integration and Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the repaired research pipeline behaves correctly with real PostgreSQL and Redis under concurrency, retries, duplicate messages, provider failures, and hostile URLs.

**Architecture:** Promote integration tests into the supported CI matrix, route retry and recovery through the same claim dispatcher, integrate the existing Redis circuit breaker into provider execution, and use database transitions as duplicate-message guards.

**Tech Stack:** PostgreSQL 16, Redis 7, Taskiq, SQLAlchemy async, pytest, GitHub Actions

---

## File Map

**Modify**

- `.github/workflows/test.yml`
- `src/research/reliability/watchdog.py`
- `src/research/tools/registry.py`
- `src/research/execution.py`
- `src/research/steps.py`
- `src/research/tasks.py`
- `tests/test_research_watchdog.py`
- `tests/test_research_circuit_breaker.py`
- `tests/test_research_security.py`

**Create**

- `tests/integration/test_research_step_claims.py`
- `tests/integration/test_research_pipeline_postgres.py`
- `tests/integration/test_research_redis_dispatch.py`
- `tests/integration/test_research_idempotency.py`
- `tests/integration/test_research_recovery.py`
- `tests/integration/test_research_workspace_isolation.py`
- `tests/smoke/test_research_live_providers.py`

## Task 1: Add PostgreSQL Concurrent-Claim Coverage

- [ ] **Step 1: Write the concurrent claim test**

Create `tests/integration/test_research_step_claims.py`. Seed two ready steps
for one task, open two independent sessions, and execute:

```python
claimed_a, claimed_b = await asyncio.gather(
    claim_one("worker-a"),
    claim_one("worker-b"),
)

assert len(claimed_a) == 1
assert len(claimed_b) == 1
assert claimed_a[0].id != claimed_b[0].id
```

Each `claim_one()` must commit before returning.

- [ ] **Step 2: Add same-step exclusion**

Seed one ready step, run two claimers, and assert the combined claimed IDs
contain the step exactly once.

Create `tests/integration/test_research_workspace_isolation.py`. Seed two
workspaces with similarly named knowledge, run concurrent retrieval, and
assert that each task persists only evidence authorized for its workspace.

- [ ] **Step 3: Run against PostgreSQL**

```bash
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run pytest \
  tests/integration/test_research_step_claims.py \
  tests/integration/test_research_workspace_isolation.py -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_research_step_claims.py \
  tests/integration/test_research_workspace_isolation.py
git commit -m "test: verify concurrent postgres step claims"
```

## Task 2: Add Redis and Taskiq Dispatch Contract

- [ ] **Step 1: Write the Redis availability fixture**

Add an opt-in `redis_client` fixture to `tests/integration/conftest.py`:

```python
@pytest_asyncio.fixture
async def redis_client():
    """提供显式配置的 Redis 集成测试客户端"""
    url = os.getenv("REDIS_URL", "")
    if not url.startswith("redis://"):
        pytest.skip("REDIS_URL is required for Redis integration tests")
    client = Redis.from_url(url, decode_responses=True)
    await client.ping()
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()
```

- [ ] **Step 2: Add dispatch integration test**

Create `tests/integration/test_research_redis_dispatch.py` with a small Taskiq
test task bound to a disposable `RedisStreamBroker`. Enqueue one step ID and
assert the broker stream contains a message without embedding the step payload
or report body.

- [ ] **Step 3: Run the Redis test**

```bash
REDIS_URL='redis://127.0.0.1:6379/15' \
DEEPSEEK_API_KEY=test \
uv run pytest tests/integration/test_research_redis_dispatch.py -q
```

Expected: all pass and Redis database 15 is empty after fixture cleanup.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/conftest.py \
  tests/integration/test_research_redis_dispatch.py
git commit -m "test: verify redis research dispatch contract"
```

## Task 3: Integrate Retry Scheduling

- [ ] **Step 1: Write retry scheduling tests**

Add tests to `tests/test_research_retrieval_flow.py`:

```python
assert step.status == ResearchStepStatus.RETRY_WAIT.value
assert step.available_at > before
assert step.owner is None
```

Add a second case where `attempt_count >= max_attempts` and assert the step is
terminally failed.

- [ ] **Step 2: Add retry transition method**

Add to `src/research/steps.py`:

```python
async def schedule_retry(
    self,
    db: AsyncSession,
    step: ResearchStep,
    *,
    delay_seconds: float,
    error: str,
) -> ResearchStep:
    """将可重试步骤安排到未来重新执行"""
    if step.attempt_count >= step.max_attempts:
        return await self.complete_step(db, step.id, error=error)
    step.status = ResearchStepStatus.RETRY_WAIT.value
    step.available_at = datetime.now(timezone.utc) + timedelta(
        seconds=delay_seconds
    )
    step.owner = None
    step.lease_expires_at = None
    step.error = error
    await db.flush()
    return step
```

- [ ] **Step 3: Use RetryPolicy in execution**

Inject `RetryPolicy` into `ResearchStepExecutor`. On a retryable
`ToolExecutionResult`, call `schedule_retry()` using:

```python
delay = self._retry.delay(
    step.attempt_count,
    tool_result.data.get("retry_after_seconds"),
)
```

- [ ] **Step 4: Promote due retries**

Add `promote_due_retries()` to `ResearchStepService`, updating due
`retry_wait` rows to `ready`. Call it from the dispatcher before claiming.

- [ ] **Step 5: Run retry tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_retry_policy.py \
  tests/test_research_retrieval_flow.py \
  tests/test_research_dispatch.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/research/execution.py src/research/steps.py \
  src/research/dispatch.py tests/test_research_retrieval_flow.py \
  tests/test_research_dispatch.py
git commit -m "feat: schedule bounded research step retries"
```

## Task 4: Route Lease Recovery Through Claiming

- [ ] **Step 1: Correct watchdog expectations**

Update `tests/test_research_watchdog.py` so recovered steps are not enqueued
directly:

```python
dispatcher.dispatch_ready.assert_awaited_once_with()
dispatcher.enqueue_step.assert_not_called()
```

- [ ] **Step 2: Change watchdog behavior**

Update `src/research/reliability/watchdog.py`:

```python
recovered = await self._steps.recover_expired_leases(db, limit=100)
promoted = await self._steps.promote_due_retries(db, limit=100)
if recovered or promoted:
    await db.commit()
    dispatched = await self._dispatcher.dispatch_ready()
else:
    dispatched = 0
return {
    "recovered": len(recovered),
    "retried": promoted,
    "dispatched": dispatched,
}
```

Also add `reconcile_pipeline_handoffs()` using PostgreSQL as the source of
truth:

- `synthesizing` with no report: re-enqueue synthesis;
- `synthesizing` with a draft report: atomically queue validation;
- `validating` without a terminal review decision: re-enqueue validation;
- `completed` with pending/failed delivery: re-enqueue delivery.

Reconciliation may enqueue duplicates, so each worker must keep the Week 1
artifact-existence and status guards. This closes the process-crash window
between a committed state transition and Taskiq enqueue.

- [ ] **Step 3: Add PostgreSQL recovery test**

Create `tests/integration/test_research_recovery.py`:

- seed an expired running lease;
- run the watchdog;
- assert a fresh claim owner and lease are persisted;
- execute the step once;
- assert no duplicate evidence row is created.

- [ ] **Step 4: Run recovery tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_watchdog.py -q

TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run pytest tests/integration/test_research_recovery.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/reliability/watchdog.py \
  tests/test_research_watchdog.py \
  tests/integration/test_research_recovery.py
git commit -m "fix: reclaim recovered research steps before enqueue"
```

## Task 5: Integrate the Provider Circuit Breaker

- [ ] **Step 1: Write registry circuit tests**

Add to `tests/test_research_tool_registry.py`:

- an open circuit returns `success=False` before provider execution;
- provider failure records a circuit failure;
- provider success clears the failure counter.

- [ ] **Step 2: Inject circuit breaker**

Extend `ResearchToolRegistry.__init__()`:

```python
def __init__(
    self,
    permission_engine=None,
    hook_bus=None,
    circuit_breaker=None,
):
    self._circuit = circuit_breaker
```

Before provider execution:

```python
provider_name = definition.provider_name or tool_name
if self._circuit is not None and not await self._circuit.allow(provider_name):
    return ToolExecutionResult(
        success=False,
        error=f"provider_circuit_open: {provider_name}",
        data={"failure_category": "provider_5xx", "retryable": True},
    )
```

Record success or failure after execution.

- [ ] **Step 3: Wire Redis circuit state**

In `src/research/tasks.py`, instantiate `ProviderCircuitBreaker` from the
existing worker Redis client and pass it to `ResearchToolRegistry`.

- [ ] **Step 4: Run circuit tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_circuit_breaker.py \
  tests/test_research_tool_registry.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/tools/registry.py src/research/tasks.py \
  tests/test_research_tool_registry.py tests/test_research_circuit_breaker.py
git commit -m "feat: enforce research provider circuit state"
```

## Task 6: Prove Stage and Delivery Idempotency

- [ ] **Step 1: Add integration test**

Create `tests/integration/test_research_idempotency.py` and concurrently invoke:

- two synthesis queue checks;
- two validation queue checks;
- two delivery jobs.

Assert controlled duplicate messages have idempotent effects:

```python
assert report_count == 1
assert delivered_message_count == 1
assert delivery.attempts == 1
```

- [ ] **Step 2: Add database locking to delivery**

Change `ResearchDeliveryService.deliver()` to load the delivery row using
`SELECT ... FOR UPDATE` when the dialect supports it. Re-check `delivered`
inside the lock before calling WeChat.

Document in the test and runbook that Enterprise WeChat does not expose a
project-controlled idempotency key: a network success followed by database
commit failure is an ambiguous external side effect, not a true exactly-once
guarantee.

- [ ] **Step 3: Run idempotency tests**

```bash
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run pytest tests/integration/test_research_idempotency.py -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/research/delivery.py \
  tests/integration/test_research_idempotency.py
git commit -m "fix: make research stage delivery idempotent"
```

## Task 7: Expand CI to the Supported Matrix

- [ ] **Step 1: Split CI jobs**

Modify `.github/workflows/test.yml` to contain:

- `unit`: SQLite-backed unit tests;
- `integration`: PostgreSQL and Redis services, Alembic upgrade, then
  `pytest tests/integration -q`.

Set:

```yaml
env:
  TEST_DATABASE_URL: postgresql+asyncpg://butler:butler@localhost:5432/butler_test
  DATABASE_URL: postgresql+asyncpg://butler:butler@localhost:5432/butler_test
  REDIS_URL: redis://localhost:6379/15
  DEEPSEEK_API_KEY: test
```

- [ ] **Step 2: Add compile and docs checks**

Add:

```yaml
- run: uv run python -m compileall -q src tests
- run: cmp -s CLAUDE.md AGENTS.md
- run: git diff --check
```

- [ ] **Step 3: Run the CI commands locally**

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
REDIS_URL='redis://127.0.0.1:6379/15' \
DEEPSEEK_API_KEY=test \
uv run pytest tests/integration -q
uv run python -m compileall -q src tests
cmp -s CLAUDE.md AGENTS.md
```

Expected: all commands exit `0`.

- [ ] **Step 4: Update operations documentation**

Update `docs/operations/research-runbook.md` with:

- integration-test service setup;
- retry and circuit inspection commands;
- lease recovery check;
- duplicate-delivery verification.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/test.yml docs/operations/research-runbook.md
git commit -m "ci: run postgres and redis research integration tests"
```

## Task 8: Add Bounded Live Provider Smoke Tests

- [ ] **Step 1: Create opt-in smoke coverage**

Create `tests/smoke/test_research_live_providers.py` with at most two cases:

- one `web.search` query;
- one structured DeepSeek synthesis using already stored evidence.

Skip unless `RUN_LIVE_RESEARCH_SMOKE=1` and the required credentials are
present. Enforce short timeouts and assert only response shape, citations to
provided evidence IDs, and non-empty normalized output.

- [ ] **Step 2: Keep smoke tests outside ordinary CI**

Do not add credentials to GitHub Actions. Add this documented manual command:

```bash
RUN_LIVE_RESEARCH_SMOKE=1 \
DEEPSEEK_API_KEY='...' \
WEB_SEARCH_ENABLED=true \
WEB_SEARCH_API_KEY='...' \
uv run pytest tests/smoke/test_research_live_providers.py -q
```

- [ ] **Step 3: Commit**

```bash
git add tests/smoke/test_research_live_providers.py \
  docs/operations/research-runbook.md
git commit -m "test: add bounded live research smoke checks"
```

## Task 9: Week 2 Gate

- [ ] **Step 1: Run security regression tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_security.py \
  tests/test_research_web_url_policy.py \
  tests/test_research_web_fetch.py \
  tests/test_research_tool_registry.py -q
```

Expected: all pass.

- [ ] **Step 2: Run the complete supported matrix**

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
REDIS_URL='redis://127.0.0.1:6379/15' \
DEEPSEEK_API_KEY=test \
uv run pytest tests/integration -q
```

Expected: all pass.

- [ ] **Step 3: Record fixed incidents**

Update `docs/agent/troubleshooting.md` with:

- definition-only providers;
- ready-but-never-dispatched steps;
- committed stage state before queue dispatch;
- direct enqueue after lease recovery;
- concurrent duplicate delivery.

- [ ] **Step 4: Commit**

```bash
git add docs/agent/troubleshooting.md
git commit -m "docs: record research reliability checks"
```
