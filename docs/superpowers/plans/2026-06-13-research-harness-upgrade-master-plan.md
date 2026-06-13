# Research Harness Upgrade Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing asynchronous research foundation into a PostgreSQL-backed, workspace-isolated, permission-governed, multi-agent research harness with validated citations.

**Architecture:** Deliver the approved design as six independently testable phases. Each phase preserves the existing private command surface, uses PostgreSQL as authoritative state, keeps Redis/Taskiq as transport, and leaves ChromaDB as the initial vector index.

**Tech Stack:** Python 3.13+, FastAPI, SQLAlchemy 2 async, PostgreSQL, asyncpg, Alembic, Redis Streams, Taskiq, LangGraph, LangChain, ChromaDB, httpx, pytest

---

## Plan Boundary

This master plan is an execution index. Implement the linked phase plans in
order. Do not combine phases into one unreviewable change set.

| Order | Plan | Working Software Produced |
|---|---|---|
| 1 | [PostgreSQL and Workspace Governance](2026-06-13-research-harness-phase1-postgres-governance.md) | PostgreSQL schema management, workspace isolation, migration command, permission and hook foundations |
| 2 | [Durable Research DAG and Approval](2026-06-13-research-harness-phase2-dag-approval.md) | Versioned plans, step dependencies, leases, atomic claims, budgets, cancellation, first-use/high-cost approval |
| 3 | [Supervisor and Retrieval Agents](2026-06-13-research-harness-phase3-supervisor-retrieval.md) | Dynamic planning, knowledge/web specialists, parallel retrieval, normalized evidence |
| 4 | [Synthesis and Citation Validation](2026-06-13-research-harness-phase4-citation-quality.md) | Claim-evidence reports, independent review, bounded repair loop |
| 5 | [Reliability, Context, and Security](2026-06-13-research-harness-phase5-reliability-security.md) | Classified retries, circuit breaking, stage contexts, SSRF and prompt-injection controls |
| 6 | [Skills, Providers, Delivery, and Evaluation](2026-06-13-research-harness-phase6-extension-operations.md) | On-demand research skills, governed provider interface, final delivery, evaluation and operations |

## Global Constraints

- Preserve `深度研究：<问题>` and `查看研究任务 <id>`.
- Keep group chat outside the research submission surface.
- Keep `source_msgid` idempotency.
- Queue payloads contain identifiers, not reports or source bodies.
- PostgreSQL is authoritative after Phase 1 cutover; do not add dual writes.
- Chroma metadata must continue to reference structured database identifiers.
- Permission decisions are independent from model intent.
- No hidden model reasoning is persisted.
- Delivery failure must not rerun research.
- Do not add shell, worktree, or coding-agent filesystem tools.
- Every Python function or method added during execution needs the Chinese
  function/input/return comments required by the repository instructions.
- Every Python file added during execution starts with a Chinese purpose and
  workflow comment block.

## Specification Coverage

| Approved design requirement | Implemented by |
|---|---|
| PostgreSQL, Alembic, one-time SQLite migration | Phase 1 Tasks 1-3, 7-9 |
| Workspace membership and isolation | Phase 1 Tasks 3, 4, 6 |
| Permission engine and lifecycle hooks | Phase 1 Task 5; integrated in Phases 1, 3, 4, 5, 6 |
| Durable task DAG, leases, retries, cancellation | Phase 2 Tasks 1-6, 8 |
| First-use and high-cost approval | Phase 2 Task 7 |
| Dynamic Supervisor planning | Phase 3 Task 5 |
| Knowledge and public-web specialists | Phase 3 Tasks 4, 6, 7 |
| Evidence provenance and deduplication | Phase 3 Task 2 |
| Claim-evidence synthesis | Phase 4 Tasks 1-3 |
| Independent citation validation | Phase 4 Tasks 4-8 |
| Bounded supplementary retrieval | Phase 4 Task 6 |
| Stage-specific context and compaction | Phase 5 Task 4 |
| Retry, circuit breaking, watchdog recovery | Phase 5 Tasks 1-3, 8 |
| SSRF and prompt-injection protection | Phase 5 Tasks 5-7 |
| On-demand Research Skills | Phase 6 Tasks 1-2 |
| Governed provider and future MCP boundary | Phase 6 Tasks 3-4 |
| Reliable WeChat delivery | Phase 6 Task 5 |
| Evaluation, traces, CI, and runbook | Phase 6 Tasks 6-10 |

## Execution Branch and Worktree

At implementation time, create an isolated worktree before Phase 1:

```bash
git status --short
git worktree add ../personal_butler_agent-research-harness \
  -b codex/research-harness-upgrade
cd ../personal_butler_agent-research-harness
```

Expected:

- the new worktree is on `codex/research-harness-upgrade`;
- the original worktree remains untouched;
- untracked files in the original worktree are not copied or deleted.

## Local Service Prerequisites

Start disposable PostgreSQL and Redis instances before Phase 1:

```bash
docker run --name butler-postgres-test --rm -d \
  -e POSTGRES_USER=butler \
  -e POSTGRES_PASSWORD=butler \
  -e POSTGRES_DB=butler_test \
  -p 5432:5432 postgres:16

docker run --name butler-redis-test --rm -d \
  -p 6379:6379 redis:7

until docker exec butler-postgres-test pg_isready -U butler; do sleep 1; done
docker exec butler-redis-test redis-cli ping
```

Expected: PostgreSQL reports `accepting connections` and Redis reports `PONG`.
Do not point tests or migrations at a production database.

## Phase Gates

### Gate 1: PostgreSQL Cutover Ready

Required before Phase 2:

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest \
  tests/integration/test_postgres_schema.py \
  tests/integration/test_postgres_knowledge_search.py -q
uv run alembic upgrade head
uv run alembic check
```

Expected: all commands exit `0`; migration validation reports no duplicate
source message IDs, no workspace-orphaned rows, and PostgreSQL keyword
retrieval returns the expected knowledge chunk.

### Gate 2: Durable DAG Ready

Required before Phase 3:

```bash
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_plan_service.py \
  tests/test_research_step_service.py \
  tests/test_research_approval.py \
  tests/integration/test_research_step_claims.py -q
```

Expected: DAG cycles are rejected, concurrent workers claim different ready
steps, expired leases recover, and first-use/high-cost plans wait for approval.

### Gate 3: Evidence Retrieval Ready

Required before Phase 4:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_supervisor.py \
  tests/test_research_source_gateway.py \
  tests/test_research_specialists.py \
  tests/test_research_evidence_service.py -q
```

Expected: structured plans persist, independent retrieval steps can run in
parallel, and every evidence row has provenance plus a content hash.

### Gate 4: Citation Quality Ready

Required before Phase 5:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_synthesizer.py \
  tests/test_research_citation_reviewer.py \
  tests/test_research_quality_flow.py -q
```

Expected: unsupported claims are repaired, weakened, or removed; only validated
reports can enter delivery.

### Gate 5: Recovery and Security Ready

Required before Phase 6:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_retry_policy.py \
  tests/test_research_circuit_breaker.py \
  tests/test_research_context.py \
  tests/test_research_web_fetch.py \
  tests/test_research_security.py -q
```

Expected: retry classes behave deterministically, external-search degradation
is explicit, private-network fetches are blocked, and source prompt injection
cannot become system instruction.

### Gate 6: Release Candidate

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
uv run alembic check
rg -n "TODO|TBD|FIXME" \
  src/research src/models/research.py docs/agent deployment.md deployment.en.md
cmp -s CLAUDE.md AGENTS.md
```

Expected: tests pass, Alembic has no pending model diff, placeholder scan is
empty, and the root agent documents are byte-identical.

## Documentation Update Matrix

Update documentation in the phase that changes the behavior:

| Change | Documentation |
|---|---|
| PostgreSQL, Alembic, workspace config | `.env.example`, `deployment.md`, `deployment.en.md`, `docs/agent/config-variables.md`, `docs/agent/decisions.md` |
| Permission, hooks, DAG, approvals | `docs/agent/patterns.md`, `docs/agent/decisions.md`, `docs/agent/active-context.md` |
| Supervisor and specialists | `docs/agent/active-context.md`, `docs/agent/patterns.md`, `CLAUDE.md`, `AGENTS.md` |
| Citation quality and report statuses | `docs/agent/active-context.md`, `docs/agent/upgrade-roadmap.md` |
| Recovery and security | `docs/agent/troubleshooting.md`, `docs/agent/patterns.md`, deployment guides |
| Skills, providers, operations | all matching docs plus worker commands and runbook |

## Final Acceptance Audit

- [ ] PostgreSQL is the only production structured-data writer.
- [ ] Workspace scope is required for research reads and writes.
- [ ] Two workers cannot claim the same step lease.
- [ ] Duplicate callbacks and queue redelivery remain idempotent.
- [ ] Ordinary plans run automatically after policy evaluation.
- [ ] First-use and high-cost plans wait for approval.
- [ ] Knowledge and web steps can execute concurrently.
- [ ] Material claims have validated evidence bindings.
- [ ] Unsupported claims do not enter final reports as facts.
- [ ] Search outages produce explicit scope limitation.
- [ ] Hard budgets and loop limits stop execution.
- [ ] Delivery retries do not rerun research.
- [ ] Existing private research commands remain compatible.
