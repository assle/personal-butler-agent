# Personal Butler Agent — 10-Minute Project Demonstration

## Setup Command Cheat Sheet

```bash
# From readiness repo root:
cd READINESS_REPO

# 1. Create venv + install deps
uv sync --extra dev

# 2. Run schema migrations
uv run alembic upgrade head

# 3. Run fast unit tests
time DEEPSEEK_API_KEY=test uv run pytest -q --ignore=tests/integration

# 4. Run full integration tests (requires PostgreSQL + Redis)
time TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
     REDIS_URL='redis://127.0.0.1:6379/15' \
     DEEPSEEK_API_KEY=test \
     uv run pytest tests/integration -q

# 5. Run evaluation
uv run butler-evaluate-research \
    --cases tests/fixtures/research_eval_cases.json \
    --output artifacts/evaluation/2026-06-interview-baseline.json

# 6. Run benchmark (requires PostgreSQL)
uv run butler-benchmark-research \
    --database-url 'postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
    --worker-counts 1,3,5 --task-count 12 \
    --output artifacts/benchmarks/2026-06-interview-baseline.json
```

---

## Minute-by-Minute Script

### Minute 0:00-1:00 — Problem Statement

**What we built**: An AI personal butler for WeChat Work teams. The core challenge: enterprise chat platforms want real-time interactive agents (sub-second reply) but also deep research capabilities (minutes of LLM time). These are fundamentally different execution models.

**Key insight**: Don't force one architecture to handle both. Use LangGraph StateGraph for interactive agents (low latency, checkpoints for conversation memory) and a durable PostgreSQL DAG with Taskiq workers for async research (lease recovery, circuit breakers, quality gates).

**Demo roadmap**: We'll walk through the interactive agent architecture, then dive into the async research pipeline, reliability mechanisms, evaluation results, and design trade-offs.

---

### Minute 1:00-2:30 — Scene Agents (Interactive)

**Key idea**: Three scene-specific LangGraph agents (private chat, group mention, webhook composition) instead of a single general-purpose controller.

**Live command** (show agent test passing):
```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_butler_agent.py -v -k "private" 2>&1 | head -20
```

**Expected output** (approximate):
```
tests/test_butler_agent.py::test_private_butler_agent_reply PASSED
tests/test_butler_agent.py::test_private_butler_weather PASSED
...
```

**Narrative**:
- Private chat: ReAct loop with 15 tools (summary, search, weather, reminders, memory CRUD, translation, knowledge ingestion)
- Group mention: Classify-then-route pattern. First classify the trigger (summarize/weather/poll/QA), then route to a focused handler. No general ReAct loop — keeps group responses predictable.
- Domain agents (Summary, Reminder, Poll) are invoked synchronously as tools, not independent ReAct agents. This keeps the architecture simple: single-agent ReAct covers 95% of personal assistant use cases.

**Trade-off to mention**: Domain agents cannot independently chain tools. If a future use case needs multi-step domain reasoning, a multi-agent Supervisor pattern would be the upgrade.

---

### Minute 2:30-5:30 — Research DAG

**Key idea**: Not a single LangGraph call — each step is a first-class DB row with leases, retry policy, and circuit breaker state.

**Pipeline steps**:
1. **Supervisor**: LLM structured-output planner produces a validated PlanDraft with typed steps, dependencies, budgets. Never searches during planning — retrieval is declared as explicit steps.
2. **Specialists**: Knowledge base and web retrieval specialists execute steps, producing ToolExecutionResult with evidence arrays. Evidence deduplication by SHA-256 of (workspace_id + source_ref + excerpt).
3. **Synthesizer**: Evidence-grounded report synthesis with claim-evidence bindings.
4. **Reviewer**: Independent citation review and validation. Receives only claims and their bound evidence — not the full report context.
5. **Quality Gate**: Deterministic local gate overrides LLM "pass" when material claims lack evidence bindings or have unresolved error findings. Bounded repair (max rounds + budget).

**Live command** (show pipeline test):
```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_pipeline.py -v 2>&1 | tail -15
```

**Expected output**:
```
tests/test_research_pipeline.py::test_research_planning_e2e PASSED
tests/test_research_pipeline.py::test_evidence_collection PASSED
tests/test_research_pipeline.py::test_synthesis_with_claims PASSED
tests/test_research_pipeline.py::test_quality_gate PASSED
tests/test_research_pipeline.py::test_repair_citation PASSED
```

**Why PostgreSQL DAG, not LangGraph**:
- Research runs take minutes, span process boundaries (producer -> queue -> worker), and need durability across worker restarts.
- LangGraph StateGraph is designed for in-process, single-invocation loops. PostgreSQL rows with leases provide the recovery that async workflows need.

---

### Minute 5:30-7:00 — Reliability

**Three mechanisms**:

1. **Exponential backoff retry**: Typed failure categories (timeout, rate_limited, execution_error) determine retry policy. Each category has per-source (provider, internal, tool) base delay, max retries, and backoff factor.

2. **Redis circuit breaker**: Opens after configurable consecutive failures. Reset after configurable cooldown. State tracked per circuit key in Redis. Prevents cascading failures when a provider is degraded.

3. **Lease watchdog**: Steps acquire leases on execution. If a worker crashes mid-step, the lease expires and another worker can reclaim. Recovery logic ensures steps are re-executed, not resumed from partial state — preventing data corruption.

**Live command**:
```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_retry_policy.py tests/test_research_circuit_breaker.py tests/test_research_watchdog.py -v 2>&1 | tail -10
```

**Expected output**:
```
tests/test_research_retry_policy.py::test_exponential_backoff PASSED
tests/test_research_circuit_breaker.py::test_circuit_opens PASSED
tests/test_research_watchdog.py::test_expired_lease_recovery PASSED
```

---

### Minute 7:00-8:30 — Evaluation

**24 evaluation cases** across 12 categories (comparison, performance, architecture, factual, howto, troubleshooting, design, security, best-practice, migration, research, data-modeling).

**Live command**:
```bash
uv run butler-evaluate-research \
    --cases tests/fixtures/research_eval_cases.json 2>&1 | tail -25
```

**If credentials are not available** (no DeepSeek key), show committed results:
```bash
python3 -m json.tool artifacts/evaluation/results.json | head -15
```

**Key metrics** (from committed results):
- Mean topic coverage: 0.78 (claims address all required sub-topics)
- Mean citation validity: 0.94 (citations support the claims they are attached to)
- Mean required source coverage: 0.99 (claims with required-source evidence)
- Mean unsupported material claim rate: 0.06 (hallucination proxy — low is good)

**Honest context**: These are deterministic measurements from offline evaluation. They indicate the pipeline produces well-structured research reports with good citation hygiene. They do not measure factual accuracy against ground truth — that requires human evaluation or a held-out answer set.

**Benchmark results** (1/2 workers, SQLite):
| Scenario | 1 Worker (t/s) | 2 Workers (t/s) |
|---|---|---|
| Normal | 6.76 | 8.17 |
| Timeout | 0.20 | 0.33 |
| Execution error | 14.81 | 46.87 |

Nearly linear scaling for parallel-dispatched errors; sub-linear for normal execution due to SQLite write contention.

---

### Minute 8:30-10:00 — Trade-offs and Q&A

**Key trade-offs to discuss**:

| Decision | Why | Trade-off |
|---|---|---|
| PostgreSQL authoritative, Redis transport | DB owns all state; queue has only task IDs | SQLite concurrent writer contention without PG |
| Scene agents, not global intent router | Clearer boundaries, easier to test, safer (group can't access private tools) | Duplicate patterns across scene agents |
| Dynamic tools default-denied | Every tool must be explicitly reviewed | Startup friction for new research tools |
| Delivery separate from execution | Failed delivery preserves completed report | Extra async hop, slight delivery delay |
| SQLite dev / PG prod | Zero-config dev; migrate when needed | Schema differences can hide bugs |
| Embedding API + local fallback | Never crash on API failure | Silent degradation if operator doesn't check logs |

**Common questions**:
- "How would you scale to 1000 users?" -> PG migration (done), connection pooling, read replicas for Chroma.
- "Why not Celery?" -> Taskiq is async-native, fewer configurations, clean integration with asyncio SQLAlchemy.
- "How do you handle prompt injection?" -> Tool gate in the research registry; URL security policy; LLM input validation.
