# Research Harness Operations Runbook

## Process Topology
- FastAPI (1 process): handles submissions, approvals, status queries
- Taskiq workers (1-3 processes): planning, steps, synthesis, validation, delivery
- PostgreSQL: authoritative state
- Redis: task queue + circuit breaker state

## Startup
```bash
uv run alembic upgrade head
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
uv run taskiq worker --ack-type when_executed --workers 3 --max-async-tasks 4 src.research.broker:broker src.research.tasks
```

## Health Checks
- PostgreSQL: `pg_isready -U butler`
- Redis: `redis-cli ping`
- Alembic: `uv run alembic check`
- Queue: check Redis Stream `butler-research` length

## Common Issues
See `docs/agent/troubleshooting.md` for detailed troubleshooting.
- Stuck steps: watchdog recovers expired leases every minute
- Circuit open: check Redis `research:circuit:*` keys; resets after configured seconds
- Approval backlog: tasks in `awaiting_approval` status

## Provenance-Limited Commands

### Evaluation (offline fixture evaluator — no DeepSeek calls)
```bash
DEEPSEEK_API_KEY=test uv run butler-evaluate-research \
    --cases tests/fixtures/research_eval_cases.json \
    --offline \
    --output artifacts/evaluation/2026-06-interview-baseline.json
```

**Provenance note**: This computes deterministic metrics from versioned fixture artifacts. No real LLM calls are made. Results indicate pipeline correctness, not production factual accuracy.

### Benchmark (PostgreSQL controlled harness — fake external deps)
```bash
DEEPSEEK_API_KEY=test uv run butler-benchmark-research \
    --database-url 'postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
    --worker-counts 1,3,5 --task-count 12 \
    --output artifacts/benchmarks/2026-06-interview-baseline.json
```

**Provenance note**: All external dependencies are mocked. Throughput numbers reflect database contention and dispatch overhead only, not real LLM or network latency. Zero duplicate claims are expected across all worker counts.

### Migration
```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
    uv run alembic upgrade head

# Verify migration state
uv run alembic check
```
