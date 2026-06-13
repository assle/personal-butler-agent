# Week 4 Interview Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the repaired and measured codebase into a truthful, repeatable ten-minute interview presentation.

**Architecture:** Treat generated test, evaluation, and benchmark artifacts as the source of truth. Documentation distinguishes implemented, optional, and reserved capabilities; diagrams explain the runtime; demo and STAR materials point back to reproducible commands.

**Tech Stack:** Markdown, Mermaid, existing project CLIs, pytest, Git

---

## File Map

**Modify**

- `README.md`
- `README.en.md`
- `PROJECT_STUDY_GUIDE.md`
- `docs/agent/active-context.md`
- `docs/agent/upgrade-roadmap.md`
- `docs/agent/troubleshooting.md`
- `docs/operations/research-runbook.md`
- `CLAUDE.md`
- `AGENTS.md`

**Create**

- `docs/interview/project-brief.md`
- `docs/interview/architecture.md`
- `docs/interview/demo-script.md`
- `docs/interview/metrics.md`
- `docs/interview/star-stories.md`
- `docs/interview/question-bank.md`

## Task 1: Reconcile Capability Claims

- [ ] **Step 1: Build a capability table**

Create `docs/interview/project-brief.md` with:

| Capability | Status | Evidence |
|---|---|---|
| WeChat callback and idempotent inbox | Implemented | callback tests and route |
| Scene Agent tool calling | Implemented | private/group graph tests |
| Chroma RAG and workspace scopes | Implemented | knowledge tests |
| Durable research DAG | Implemented after Week 1 | pipeline and PostgreSQL tests |
| Citation quality gate | Implemented after Week 1 | review and delivery tests |
| Retry/circuit/lease recovery | Implemented after Week 2 | reliability tests |
| Deterministic evaluation | Implemented after Week 3 | evaluation artifact |
| Full MCP runtime | Reserved | no production transport |
| Model fine-tuning | Out of scope | not claimed |

- [ ] **Step 2: Correct root documentation**

Update `README.md`, `README.en.md`, and `PROJECT_STUDY_GUIDE.md` so:

- fixed-score evaluation language is removed;
- MCP is called a reserved governed boundary;
- research pipeline stages match actual worker wiring;
- current test and metric commands are included;
- no production user count or throughput is invented.

- [ ] **Step 3: Correct project memory**

Update `docs/agent/active-context.md` and
`docs/agent/upgrade-roadmap.md`:

- mark CI complete only after Gate 2;
- mark evaluation complete only after Gate 3;
- keep Docker and live E2E tests as future work if still absent.

- [ ] **Step 4: Mirror root agent docs**

If architecture or purpose changes require root updates:

```bash
cp CLAUDE.md AGENTS.md
cmp -s CLAUDE.md AGENTS.md
```

- [ ] **Step 5: Run documentation checks**

```bash
rg -n "fixed perfect|全部完成|完整 MCP|生产级|正式用户|高并发" \
  README.md README.en.md PROJECT_STUDY_GUIDE.md docs/agent docs/interview
cmp -s CLAUDE.md AGENTS.md
git diff --check
```

Expected: every strong claim is either supported by an evidence link or
rewritten conservatively.

- [ ] **Step 6: Commit**

```bash
git add README.md README.en.md PROJECT_STUDY_GUIDE.md \
  docs/agent docs/interview/project-brief.md CLAUDE.md AGENTS.md
git commit -m "docs: align research capabilities with evidence"
```

## Task 2: Create Interview Architecture Diagrams

- [ ] **Step 1: Add the system diagram**

Create `docs/interview/architecture.md` with this Mermaid diagram:

```mermaid
flowchart LR
    W["WeChat Work callback"] --> I["Idempotent inbox"]
    I --> S["Scene dispatch"]
    S --> P["PrivateButlerAgent"]
    P --> R["Research submission"]
    R --> Q["Taskiq / Redis"]
    Q --> D["PostgreSQL research DAG"]
    D --> K["Knowledge provider"]
    D --> E["Web provider"]
    K --> V["Evidence store"]
    E --> V
    V --> Y["Synthesis"]
    Y --> C["Citation review"]
    C -->|pass| O["Validated report"]
    C -->|repair| D
    O --> M["WeChat app delivery"]
```

- [ ] **Step 2: Add the sequence diagram**

```mermaid
sequenceDiagram
    participant U as User
    participant A as FastAPI
    participant P as PostgreSQL
    participant Q as Taskiq
    participant W as Worker
    participant T as Tool Registry
    participant R as Reviewer

    U->>A: 深度研究 request
    A->>P: create task by source_msgid
    A->>Q: enqueue planning(task_id)
    W->>P: persist plan and ready steps
    W->>P: claim ready steps with SKIP LOCKED
    W->>Q: enqueue claimed step IDs
    W->>T: execute governed provider
    T->>P: persist normalized evidence
    W->>P: transition to synthesizing
    W->>R: validate claim-evidence bindings
    R->>P: mark validated or create repair steps
    W->>U: proactive private delivery
```

- [ ] **Step 3: Add trade-off notes**

Explain:

- why PostgreSQL is authoritative and Redis is transport;
- why scene agents remain LangGraph while research uses a durable DAG;
- why dynamic tools default to denied;
- why delivery is separate from research execution.

- [ ] **Step 4: Commit**

```bash
git add docs/interview/architecture.md
git commit -m "docs: add research interview architecture diagrams"
```

## Task 3: Write the Ten-Minute Demo

- [ ] **Step 1: Create setup commands**

In `docs/interview/demo-script.md`, include:

```bash
uv sync --extra dev
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
DEEPSEEK_API_KEY=test \
uv run alembic upgrade head
DEEPSEEK_API_KEY=test uv run pytest -q
```

- [ ] **Step 2: Define minute-by-minute delivery**

Use:

1. `0:00-1:00`: business problem and real WeChat boundary;
2. `1:00-2:30`: scene agents and RAG;
3. `2:30-5:30`: durable research pipeline;
4. `5:30-7:00`: failure recovery and safety;
5. `7:00-8:30`: evaluation and benchmark results;
6. `8:30-10:00`: trade-offs and next steps.

- [ ] **Step 3: Add live commands**

Include:

```bash
uv run pytest \
  tests/test_research_pipeline.py::test_full_research_pipeline_reaches_delivery \
  -q

uv run butler-evaluate-research \
  --cases tests/fixtures/research_eval_cases.json \
  --output /tmp/butler-eval.json

uv run python -m json.tool /tmp/butler-eval.json | sed -n '1,80p'
```

- [ ] **Step 4: Add fallback presentation**

If external credentials or WeChat are unavailable, use deterministic pipeline
tests and committed artifacts. Explicitly state that external APIs are mocked
in the demo rather than pretending the call is live.

- [ ] **Step 5: Rehearse**

Run the script from a clean worktree and record actual duration. Shorten any
section that makes the total exceed ten minutes.

- [ ] **Step 6: Commit**

```bash
git add docs/interview/demo-script.md
git commit -m "docs: add ten minute project demonstration"
```

## Task 4: Publish the Metrics Sheet

- [ ] **Step 1: Generate metrics**

Read:

- `artifacts/evaluation/2026-06-interview-baseline.json`;
- `artifacts/benchmarks/2026-06-interview-baseline.json`;
- latest pytest result.

- [ ] **Step 2: Create `docs/interview/metrics.md`**

Include:

- environment and date;
- dataset size;
- mean topic coverage;
- citation validity;
- unsupported material claim rate;
- required source coverage;
- total estimated cost;
- worker-count latency and throughput table;
- retry and failure scenarios;
- explicit limitations.

Every number must reference its artifact path and generation command.

- [ ] **Step 3: Add resume-safe statements**

Use wording such as:

> Built a PostgreSQL-backed asynchronous Agent research pipeline with durable
> DAG execution, workspace isolation, governed retrieval, citation validation,
> and idempotent WeChat delivery; validated with N deterministic evaluation
> cases and controlled 1/3/5-worker benchmarks.

Replace `N` with the measured case count. Do not claim production QPS or real
users without evidence.

- [ ] **Step 4: Commit**

```bash
git add docs/interview/metrics.md
git commit -m "docs: publish reproducible research metrics"
```

## Task 5: Prepare STAR Stories

- [ ] **Step 1: Create four stories**

Create `docs/interview/star-stories.md`:

1. **Pipeline correctness:** ready steps were never claimed or dispatched.
2. **Provider architecture:** definitions existed without executable providers.
3. **Reliability:** recovered leases were enqueued without a fresh claim.
4. **Evaluation honesty:** fixed perfect scores were replaced by calculated
   metrics.

- [ ] **Step 2: Use the same structure**

For each story:

- Situation: the concrete defect and user impact;
- Task: the invariant to restore;
- Action: files, transaction boundary, tests, and trade-offs;
- Result: passing test or measured artifact;
- Reflection: what would change at larger scale.

- [ ] **Step 3: Commit**

```bash
git add docs/interview/star-stories.md
git commit -m "docs: add research engineering star stories"
```

## Task 6: Build the Technical Question Bank

- [ ] **Step 1: Create question categories**

Create `docs/interview/question-bank.md` with at least:

- 12 Python async questions;
- 12 PostgreSQL and transaction questions;
- 10 Redis/Taskiq/message-delivery questions;
- 12 Agent planning/tool questions;
- 12 RAG and citation questions;
- 10 reliability/security questions;
- 8 system-design questions;
- 10 project-deep-dive questions.

- [ ] **Step 2: Include required project questions**

Answer:

- Why LangGraph for scene agents but a durable DAG for research?
- How does `SKIP LOCKED` prevent double claims?
- What happens if Redis enqueue fails after PostgreSQL claim commit?
- How is duplicate callback delivery handled?
- Why is exactly-once delivery not claimed?
- How are RAG knowledge updates made visible?
- How do you measure unsupported claims?
- How does the system stop prompt injection from fetched pages?
- Why is MCP still reserved?
- What evidence proves the project works?

- [ ] **Step 3: Add two coding exercises**

Include:

- implement exponential backoff with jitter;
- design an idempotent queue consumer using a database key.

- [ ] **Step 4: Commit**

```bash
git add docs/interview/question-bank.md
git commit -m "docs: add agent backend interview question bank"
```

## Task 7: Final Acceptance Audit

- [ ] **Step 1: Run all tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
REDIS_URL='redis://127.0.0.1:6379/15' \
DEEPSEEK_API_KEY=test \
uv run pytest tests/integration -q
```

Expected: all pass.

- [ ] **Step 2: Regenerate evidence**

```bash
uv run butler-evaluate-research \
  --cases tests/fixtures/research_eval_cases.json \
  --output artifacts/evaluation/2026-06-interview-baseline.json

uv run butler-benchmark-research \
  --database-url 'postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  --worker-counts 1,3,5 \
  --task-count 12 \
  --output artifacts/benchmarks/2026-06-interview-baseline.json
```

- [ ] **Step 3: Validate documentation**

```bash
git diff --check
cmp -s CLAUDE.md AGENTS.md
rg -n "TODO|TBD|FIXME" \
  README.md README.en.md PROJECT_STUDY_GUIDE.md \
  docs/interview docs/agent docs/operations/research-runbook.md
```

Expected: all commands exit `0`.

- [ ] **Step 4: Rehearse the demo**

Follow `docs/interview/demo-script.md` from top to bottom without undocumented
commands or manual database edits.

- [ ] **Step 5: Commit final audit updates**

```bash
git add README.md README.en.md PROJECT_STUDY_GUIDE.md \
  docs/interview docs/agent docs/operations/research-runbook.md \
  artifacts/evaluation/2026-06-interview-baseline.json \
  artifacts/benchmarks/2026-06-interview-baseline.json
git commit -m "docs: finalize interview ready research project"
```

