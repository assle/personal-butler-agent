# Interview-Readiness Remediation Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Personal Butler Agent a credible, measurable, ten-minute interview project for large-model application and Agent backend roles in four weeks.

**Architecture:** Repair the existing research harness instead of adding another feature layer. PostgreSQL remains authoritative, Taskiq/Redis transport identifiers, governed providers produce persisted evidence, deterministic quality gates control delivery, and evaluation artifacts provide reproducible interview metrics.

**Tech Stack:** Python 3.13+, FastAPI, LangChain, LangGraph, SQLAlchemy 2 async, PostgreSQL 16, Redis 7, Taskiq, ChromaDB, Alembic, pytest, GitHub Actions

---

## Plan Index

Implement the phase plans in order.

| Week | Plan | Exit Result |
|---|---|---|
| 1 | [Executable Research Pipeline](2026-06-13-interview-readiness-week1-pipeline.md) | Submission, planning, retrieval, synthesis, review, and delivery run as one tested path |
| 2 | [Integration and Reliability](2026-06-13-interview-readiness-week2-reliability.md) | PostgreSQL/Redis CI, concurrency, retry, security, and idempotency evidence |
| 3 | [Evaluation and Metrics](2026-06-13-interview-readiness-week3-evaluation.md) | 20+ deterministic cases plus quality, latency, cost, and concurrency reports |
| 4 | [Interview Presentation](2026-06-13-interview-readiness-week4-presentation.md) | Clean documentation, ten-minute demo, architecture diagrams, STAR stories, and question bank |

## Scope Rules

- Do not add new chat capabilities.
- Do not implement full MCP transport.
- Do not add model training or fine-tuning.
- Do not claim a capability as complete until its phase gate passes.
- Preserve `深度研究：<问题>` and `查看研究任务 <id>`.
- Preserve callback `source_msgid` idempotency.
- Queue payloads contain identifiers, not reports or source bodies.
- Keep `CLAUDE.md` and `AGENTS.md` byte-for-byte identical.
- Follow the repository requirement for Chinese Python file and function comments.
- For every new `.py` file, add the required Chinese purpose/workflow comment
  block; for every new function or method, document purpose, parameters, and
  return value in Chinese.
- Treat Taskiq delivery as at-least-once. Prove idempotent database effects and
  prevent concurrent duplicate sends; document the ambiguous outcome when an
  external send succeeds but its database commit fails.
- Do not edit or remove the existing `.claude/worktrees/phase1-postgres-governance` entry.

## Recommended Worktree

Before implementation:

```bash
git status --short
git worktree add ../personal_butler_agent-interview \
  -b codex/interview-readiness-remediation main
cd ../personal_butler_agent-interview
```

Expected:

- the branch is `codex/interview-readiness-remediation`;
- the original checkout remains unchanged;
- only committed files are copied into the worktree.

## Service Setup

Use disposable local services:

```bash
docker run --name butler-interview-pg --rm -d \
  -e POSTGRES_USER=butler \
  -e POSTGRES_PASSWORD=butler \
  -e POSTGRES_DB=butler_test \
  -p 5432:5432 postgres:16

docker run --name butler-interview-redis --rm -d \
  -p 6379:6379 redis:7

until docker exec butler-interview-pg pg_isready -U butler; do sleep 1; done
docker exec butler-interview-redis redis-cli ping
```

Expected: PostgreSQL reports `accepting connections`; Redis reports `PONG`.

## Four-Week Calendar

### Week 1: 18 hours

| Day | Time | Work |
|---|---:|---|
| Day 1 | 3h | Repair the remaining baseline failure and lock the green unit baseline |
| Day 2 | 4h | Correct provider interfaces and assemble executable built-in providers |
| Day 3 | 4h | Implement ready-step claim, dispatch, and enqueue rollback |
| Day 4 | 4h | Wire synthesis, validation, repair, and delivery transitions |
| Day 5 | 3h | Add deterministic full-pipeline test and run the Week 1 gate |

### Week 2: 17 hours

| Day | Time | Work |
|---|---:|---|
| Day 1 | 4h | Add PostgreSQL claim-concurrency and workspace integration tests |
| Day 2 | 3h | Add Redis/Taskiq dispatch contract and CI service checks |
| Day 3 | 4h | Integrate retry scheduling, lease recovery, and circuit breaker |
| Day 4 | 3h | Add duplicate-stage and duplicate-delivery tests |
| Day 5 | 3h | Add security regression matrix and run the Week 2 gate |

### Week 3: 18 hours

| Day | Time | Work |
|---|---:|---|
| Day 1 | 4h | Define evaluation case/artifact schemas and metric formulas |
| Day 2 | 4h | Implement deterministic evaluator and CLI exports |
| Day 3 | 3h | Build 20-30 evaluation fixtures |
| Day 4 | 4h | Add trace propagation and stage measurements |
| Day 5 | 3h | Run concurrency/failure benchmark and freeze results |

### Week 4: 15 hours

| Day | Time | Work |
|---|---:|---|
| Day 1 | 3h | Reconcile README, active context, roadmap, and operations docs |
| Day 2 | 3h | Write demo script and clean-checkout setup |
| Day 3 | 3h | Produce architecture and sequence diagrams |
| Day 4 | 3h | Write STAR stories and technical question bank |
| Day 5 | 3h | Rehearse, rerun evidence commands, and complete acceptance audit |

## Weekly Gates

### Gate 1: Executable Pipeline

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_pipeline.py \
  tests/test_research_provider_registry.py \
  tests/test_research_tasks.py -q
```

Expected:

- no unit-test failure;
- the deterministic pipeline reaches `delivered`;
- no production registry tool lacks a provider.

### Gate 2: Integration and Reliability

```bash
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
REDIS_URL='redis://127.0.0.1:6379/15' \
DEEPSEEK_API_KEY=test \
uv run pytest tests/integration -q
```

Expected:

- concurrent claimers never receive the same step;
- duplicate stage messages do not duplicate reports or delivery;
- lease recovery and retry scheduling pass;
- private and link-local URLs remain blocked.

### Gate 3: Metrics

```bash
uv run butler-evaluate-research \
  --cases tests/fixtures/research_eval_cases.json \
  --output artifacts/evaluation/latest.json

uv run butler-benchmark-research \
  --database-url 'postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  --worker-counts 1,3,5 \
  --output artifacts/benchmarks/latest.json
```

Expected:

- at least 20 case results;
- metrics are derived and non-constant;
- benchmark output includes worker count, throughput, success rate, latency,
  retries, and duplicate count.

### Gate 4: Interview Release

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
git diff --check
cmp -s CLAUDE.md AGENTS.md
rg -n "TODO|TBD|FIXME" \
  README.md PROJECT_STUDY_GUIDE.md docs/interview docs/agent \
  docs/operations/research-runbook.md
```

Expected:

- commands exit `0`;
- documentation does not call reserved MCP, fixed-score evaluation, or
  unverified tracing a complete runtime capability;
- the demo can be executed from `docs/interview/demo-script.md`.

## Final Acceptance Checklist

- [ ] Unit and integration test suites are green.
- [ ] CI runs PostgreSQL and Redis integration tests.
- [ ] Built-in research tools have executable providers.
- [ ] Ready steps are atomically claimed before enqueue.
- [ ] Enqueue failure safely releases a claim.
- [ ] Dependent steps dispatch after prerequisites complete.
- [ ] Duplicate synthesis and validation messages have idempotent effects, and
  stuck handoffs can be replayed from PostgreSQL state.
- [ ] Only validated reports are delivered.
- [ ] Delivery text contains the validated report, not the Phase 1 disclaimer.
- [ ] Evaluation contains at least 20 cases and calculated metrics.
- [ ] Trace IDs are persisted on tasks/events, and task/step IDs join usage,
  review, and delivery records to the same trace.
- [ ] Benchmark and failure results are versioned under `artifacts/`.
- [ ] README and project memory match the code.
- [ ] A ten-minute demo and interview question bank exist.
