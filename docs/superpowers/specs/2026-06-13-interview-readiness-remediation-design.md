# Interview-Readiness Remediation Design

## 1. Goal

Use four weeks at 15-20 hours per week to turn Personal Butler Agent into a
credible interview project for large-model application and Agent backend
roles.

The project must move from "many designed capabilities" to demonstrable
engineering evidence:

- the asynchronous research pipeline runs end to end;
- automated tests and CI are green;
- Agent and RAG quality are measured with reproducible evaluation cases;
- latency, cost, reliability, and security results can be explained;
- the project can be demonstrated and defended in a ten-minute interview.

## 2. Guiding Principle

The work follows this order:

1. Correctness before feature breadth.
2. Real runtime wiring before documentation claims.
3. Reproducible measurements before resume wording.
4. Interview evidence before production-scale infrastructure.

No new user-facing capability should be added until the research pipeline and
verification baseline are trustworthy.

## 3. Current Problems

### 3.1 Research execution is not fully wired

The worker registry declares research tools without attaching executable
providers. Planning can mark root steps ready, while step workers expect an
already claimed running step. The normal path therefore lacks a complete
ready-to-claim-to-dispatch transition.

The synthesis, validation, and delivery stages also need explicit dispatch
handoffs and idempotency checks so duplicate workers cannot repeat terminal
actions.

### 3.2 Verification is not green

The local suite currently reports two failures:

- the structured LLM test uses an asynchronous mock for a synchronous
  `with_structured_output()` factory;
- a Settings test passes an environment-style uppercase name as a constructor
  field.

CI starts PostgreSQL and Redis but excludes the integration test directory.
There is no single command proving that the complete supported test matrix is
green.

### 3.3 Evaluation and observability are mostly interfaces

The offline evaluation runner returns fixed perfect scores instead of deriving
metrics from reports, claims, evidence, cost, and latency. `TraceContext`
defines identifiers but is not propagated through the complete API, queue,
worker, tool, synthesis, review, and delivery flow.

### 3.4 Interview evidence is missing

The repository does not yet contain reproducible evidence for:

- research success and failure rates;
- citation validity and unsupported-claim rate;
- retrieval coverage;
- end-to-end and stage latency;
- token and estimated monetary cost;
- duplicate delivery prevention;
- worker failure and lease recovery;
- concurrent workspace isolation.

## 4. Scope

### 4.1 Included

- Repair the current unit-test failures.
- Complete the asynchronous research runtime wiring.
- Bind real built-in knowledge and web providers to the governed registry.
- Add a dispatcher loop for ready-step claiming and Taskiq enqueueing.
- Complete synthesis, validation, repair, and delivery handoffs.
- Add realistic PostgreSQL and Redis integration tests.
- Add bounded external-provider smoke tests that are opt-in and never run on
  ordinary pull requests.
- Replace fixed evaluation results with deterministic metric computation.
- Propagate trace identifiers and structured stage events.
- Create a 20-30 case evaluation dataset.
- Run a small concurrency and failure-recovery benchmark.
- Produce interview-facing architecture, metrics, demonstration, and question
  preparation material.

### 4.2 Excluded

- Model training, LoRA, DPO, or other algorithm-role preparation.
- A general coding-agent shell, filesystem sandbox, worktree manager, or
  autonomous agent team.
- A full MCP transport implementation.
- Kubernetes, service mesh, or large-scale production deployment.
- A new administration frontend.
- New chat capabilities unrelated to the research pipeline.

## 5. Target Runtime Flow

```text
WeChat private callback
  -> idempotent research submission
  -> planning task
  -> structured Supervisor plan
  -> plan validation and approval decision
  -> root steps become ready
  -> dispatcher atomically claims ready steps
  -> Taskiq executes claimed steps
  -> governed knowledge/web providers return normalized evidence
  -> completed steps unlock and dispatch dependents
  -> all required steps complete
  -> synthesis task
  -> citation review
  -> bounded repair or validated report
  -> idempotent delivery task
  -> Enterprise WeChat private message
```

PostgreSQL remains authoritative for task state. Redis transports identifiers
and stores transient coordination state. Workers must be able to retry from
database state without relying on in-memory conversation history.

## 6. Component Design

### 6.1 Provider assembly

Create one worker-side assembly function that registers definitions and
executable providers together.

- `knowledge.search` uses `ResearchSourceGateway` and `KnowledgeResearcher`.
- `web.search` uses `WebSearchService` and `WebResearcher`.
- `web.fetch` uses the secured full-page fetcher when the plan requests it.

The function receives dependencies explicitly. Tests can substitute fake
providers without importing the production worker module.

### 6.2 Ready-step dispatcher

Add a service that:

1. opens a database transaction;
2. claims up to the configured concurrency limit with `FOR UPDATE SKIP LOCKED`;
3. commits the ownership and lease;
4. enqueues each claimed step ID;
5. records a dispatch event.

The same service is called after plan activation, approval, dependent-step
unblocking, and lease recovery. Enqueue failure returns the step to a retryable
ready state instead of leaving it running until lease expiry.

### 6.3 Pipeline transitions

Every stage owns one explicit transition:

- planning activates or waits for approval;
- step completion dispatches newly ready dependents;
- completion of the required DAG dispatches synthesis once;
- synthesis dispatches validation once;
- validation either dispatches repair steps, fails, or marks the report
  validated and dispatches delivery;
- delivery records attempts and refuses to resend an already delivered report.

Database state and idempotency constraints are the authoritative guards.

### 6.4 Evaluation

Evaluation cases contain:

- question and category;
- expected key topics;
- required source characteristics;
- known unsupported traps;
- maximum acceptable unsupported-claim rate.

The evaluator derives:

- topic coverage;
- citation validity;
- unsupported material claim rate;
- required source coverage;
- latency;
- estimated cost.

The default evaluator works from stored deterministic fixtures. An opt-in live
runner may call external providers and DeepSeek when credentials are supplied.

### 6.5 Observability

A trace ID is created at submission and persisted with the research task.
Every event includes:

- trace, workspace, task, step, and attempt identifiers;
- stage name and outcome;
- elapsed milliseconds;
- provider and model when applicable;
- token and estimated cost information;
- failure category and retry decision.

The interview milestone requires structured logs and PostgreSQL events, not a
full telemetry backend.

## 7. Four-Week Delivery

### Week 1: Correctness and executable pipeline

- Fix the two existing test failures.
- Replace definition-only tool registration with provider assembly.
- Implement ready-step claim and dispatch.
- Wire plan, step, synthesis, validation, and delivery transitions.
- Add one deterministic end-to-end research test.

Exit gate:

- the ordinary non-approval path completes from submission to delivery;
- an approval path resumes correctly;
- the complete local unit suite passes.

### Week 2: Integration and reliability

- Run PostgreSQL integration tests in CI.
- Add Redis/Taskiq dispatch contract tests.
- Test concurrent step claims and workspace isolation.
- Test duplicate callback, duplicate synthesis, and duplicate delivery.
- Test worker interruption, lease recovery, provider timeout, and circuit
  opening.
- Verify SSRF and unapproved-tool rejection.

Exit gate:

- CI is green;
- no duplicate report or delivery occurs under retry;
- failure recovery has deterministic test evidence.

### Week 3: Evaluation and measurements

- Replace fixed scores with real deterministic metric calculation.
- Build 20-30 evaluation cases across factual research, comparison, internal
  knowledge, conflicting sources, and insufficient evidence.
- Record quality, latency, token, and cost metrics.
- Run a small concurrency benchmark with 1, 3, and 5 workers.
- Record at least three controlled failure scenarios.

Exit gate:

- evaluation and benchmark commands produce versioned JSON or Markdown
  results;
- every resume metric can be reproduced by a documented command.

### Week 4: Interview presentation

- Correct project documentation so implemented and reserved capabilities are
  clearly separated.
- Prepare a ten-minute demonstration script.
- Prepare one architecture diagram and one research sequence diagram.
- Prepare STAR explanations for reliability, RAG quality, multi-tenant
  isolation, and architecture trade-offs.
- Prepare likely follow-up questions covering Python async, PostgreSQL,
  Redis/queues, idempotency, RAG, Agent planning, and failure recovery.

Exit gate:

- a clean checkout can follow the demonstration instructions;
- the project can be explained without claiming unmeasured scale or unfinished
  MCP/Eval capabilities.

## 8. Test Strategy

### Unit tests

- provider registration and permission ordering;
- plan validation and state transitions;
- evaluator metric calculations;
- retry, circuit, URL, and idempotency behavior.

### Integration tests

- PostgreSQL migrations and `SKIP LOCKED` claims;
- Taskiq dispatch with Redis;
- workspace isolation;
- evidence persistence through synthesis and review;
- delivery idempotency.

### Opt-in live smoke tests

- one real structured DeepSeek response;
- one real web search;
- one full research request with a strict maximum cost.

Live tests require explicit environment variables and are excluded from normal
CI.

## 9. Interview Acceptance Criteria

The remediation is complete only when all of the following are true:

1. `uv run pytest -q` passes with no unexpected skips.
2. The CI job runs the supported PostgreSQL and Redis integration matrix.
3. One command demonstrates the full research pipeline.
4. Twenty or more evaluation cases produce calculated, non-constant metrics.
5. Benchmark results include end-to-end latency, stage latency, success rate,
   citation validity, unsupported-claim rate, and estimated cost.
6. Duplicate submission and delivery are proven idempotent.
7. Worker interruption and provider failure recovery are demonstrated.
8. Documentation distinguishes implemented, optional, and reserved features.
9. Resume claims cite a reproducible result or avoid numeric claims.
10. The ten-minute demonstration succeeds from a clean documented setup.

## 10. Documentation Updates

During implementation:

- update `docs/agent/active-context.md` only after runtime wiring is proven;
- revise `docs/agent/upgrade-roadmap.md` to remove stale CI and completion
  statements;
- add reproducible checks to `docs/operations/research-runbook.md`;
- update `docs/agent/troubleshooting.md` for each reproducible failure fixed;
- keep `CLAUDE.md` and `AGENTS.md` byte-for-byte identical if either changes.

The project must not describe interfaces, placeholders, or reserved adapters as
fully operational capabilities.
