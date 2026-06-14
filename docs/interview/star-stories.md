# Personal Butler Agent — STAR Engineering Stories

---

## Story 1: Pipeline Correctness — Ready Steps Never Dispatched

**Situation**: The research DAG has a step dependency system: a step with status `pending` must not be dispatched for execution until all its dependencies are `completed`. Early integration tests showed the dispatcher occasionally advancing steps whose prerequisites were still `pending` or `failed`.

**Task**: Make the step dispatch logic provably correct: a step should transition from `pending` to `ready` only when every dependency has `completed` status. This is a safety-critical invariant — executing steps out of order produces garbage research reports.

**Action**:
- Audited the `StepDispatcher.dispatch_pending` logic. Found that the original SQL query selected steps by filtering on `status = 'pending'` but only checked dependency completion in application code after fetching, risking a race between the fetch and the status update.
- Refactored the dispatch to use a single SQL query with a `NOT EXISTS` subquery filtering for steps whose dependencies still have non-completed statuses. This made the check atomic: only steps whose dependencies are provably `completed` at query time are returned.
- Added an integration test (`test_research_step_claims.py`) that creates a dependency chain (step C depends on step B, step B depends on step A), marks only step A as completed, and asserts that only step B becomes ready while step C stays pending.

**Result**: Zero reported incidents of out-of-order step execution. The `NOT EXISTS` pattern became the standard for all dependency-gated operations in the codebase.

**Reflection**: This was a case where application-level correctness was insufficient — the database-level invariant was the right enforcement point. The fetch-and-check pattern would have been a latent bug waiting for a race condition in production.

---

## Story 2: Provider Architecture — Definitions Without Providers

**Situation**: The research pipeline needs to support multiple provider backends (knowledge base, web search, LLM, and future MCP servers). The Phase 6 design specified an MCP (Model Context Protocol) provider interface. I needed to decide: implement a full MCP transport layer now, or define the contract and defer.

**Task**: Design a provider architecture that supports future MCP integration without building the transport layer before it's needed.

**Action**:
- Defined the `ResearchProvider` protocol in `src/research/providers/` with abstract methods for tool registration, capability discovery, and execution. This is the contract that any future provider (including MCP) must implement.
- Implemented only the built-in providers: `BuiltinResearchDependencies` registers knowledge search, web search, and LLM completion as available tools. These use the internal tool registry (`ResearchToolRegistry`) with permission checks.
- Reserved the MCP namespace (`src/research/providers/mcp.py`) with a stub that documents the expected interface but raises `NotImplementedError`. Added a comment explaining what transport layer (stdio or SSE) it would use when implemented.
- Documented the provider boundary in `docs/agent/decisions.md` as ADR-031 and ADR-033 with explicit trade-offs.

**Result**: The provider architecture supports two built-in backends with a defined extension point for MCP. No dead code, no untested transport. When MCP integration is prioritized, the implementer follows the established protocol.

**Reflection**: Defining a contract without implementing it might feel incomplete, but it creates a clean extension boundary. Had I built the MCP transport speculatively, it would have been untested code with no real consumer. The stub acts as an unambiguous signal to future developers: "this is where MCP goes, and this is how it connects."

---

## Story 3: Reliability — Recovered Leases Without Fresh Claims

**Situation**: The research step execution uses a lease system: when a worker claims a step, it writes a lease timestamp to the database. If the worker crashes, the lease expires and another worker should recover it. The original implementation had a bug: the recovery logic would first release the expired lease, then attempt a fresh claim. In a multi-worker setup, this created a window where a second worker could steal the step before the first completed its recovery.

**Task**: Implement lease recovery that transitions a timed-out step directly from `running` back to `pending` without a separate release-and-claim sequence, eliminating the race.

**Action**:
- Analyzed the lease recovery code in `src/research/reliability/watchdog.py`. Found the race: `release_lease()` set the step status to `pending`, then `claim_step()` tried to set it to `running` with a new lease. Between these two operations, another worker's watchdog could observe `pending` and claim the step.
- Replaced the two-step sequence with a single atomic `UPDATE ... SET status = 'pending', lease_expires_at = NULL WHERE status = 'running' AND lease_expires_at < NOW()`. The step transitions directly from `running` to `pending` in one operation. Any worker can then claim it normally.
- Added a watchdog integration test (`test_expired_lease_recovery`) that starts a step, advances the clock past the lease expiry, and verifies the step is recovered to `pending` without transitioning through any intermediate state.

**Result**: The race window is eliminated. Multiple workers can safely coexist, each running its watchdog independently. The lease recovery test passes consistently with no flakiness.

**Reflection**: This was a classic TOCTOU (time-of-check-time-of-use) bug in a distributed system. The fix was to make the state transition atomic at the database level. A reminder that in multi-worker systems, you need to think in terms of database transactions, not code sequences.

---

## Story 4: Evaluation Honesty — Fixed Scores Replaced by Calculated Metrics

**Situation**: The Phase 4 evaluation runner was returning hardcoded perfect scores for every evaluation case. When I joined the project, the evaluation output showed `claim_topic_coverage: 1.0`, `citation_validity: 1.0`, and `unsupported_material_claim_rate: 0.0` for all 24 cases. These "fixed perfect scores" made the evaluation pipeline a ceremonial pass-through rather than an actual quality measurement.

**Task**: Replace the hardcoded scores with real calculated metrics derived from the actual research pipeline output, and ensure the evaluation produces honest, reproducible numbers.

**Action**:
- Audited the evaluation runner (`src/research/evaluation/`). Found that the original implementation skipped the actual pipeline execution for each case and returned hardcoded constants. It was written during early Phase 4 when the pipeline wasn't fully wired, and was never updated.
- Replaced the fixed values with real metric computation. For each of the 24 cases, the runner now:
  1. Executes the full pipeline (Supervisor -> Specialists -> Synthesizer -> Reviewer -> Quality Gate)
  2. Measures `claim_topic_coverage`: proportion of required sub-topics addressed in the output report
  3. Measures `citation_validity`: proportion of claims where cited sources support the claim text
  4. Measures `unsupported_material_claim_rate`: proportion of material claims without evidence bindings
  5. Measures `required_source_coverage`: proportion of claims that cite required sources
  6. Records latency and token cost
- Updated the evaluation CLI to accept `--output` for reproducibility and added the `generated_at` timestamp.
- Re-ran the evaluation. The results (now in `artifacts/evaluation/results.json`) show real variance: coverage ranges from 0.0 to 1.0, citation validity from 0.67 to 1.0. Mean topic coverage is 0.78 — not 1.0.

**Result**: The evaluation now produces honest, actionable metrics. The output reveals real quality differences between case categories (factual/howto/troubleshooting cases score perfectly; design/research/migration cases show gaps — the harder the case, the more the pipeline struggles). This data directly informs the Phase 4 quality gate thresholds and repair budget allocation.

**Reflection**: Fixed perfect scores felt like a "maintenance shortcut" but were actually hiding the entire evaluation's lack of value. The moment I replaced them with real computation, we discovered meaningful quality gaps. The lesson: any metric that always returns the same value is not measuring anything. If you can't tolerate the real metric, fix the pipeline, not the measurement.

## Additional STAR-Light Stories

### 4b. Task Status Query Without Full Table Scan

**Situation**: The private research submission endpoint needed a status lookup for "查看研究任务 R-xxx". The initial implementation loaded all research tasks for the user and filtered in Python.

**Task**: Implement an efficient single-row lookup by task ID without loading unrelated tasks.

**Action**: Added a `get_task_by_id()` method to `ResearchTaskService` that queries by `task_id` with a `user_id` filter in SQL. The indexes on `research_tasks(task_id)` and `research_tasks(user_id)` ensure O(log n) lookups. The response is a single-row `SELECT ... WHERE task_id = ? AND user_id = ?`.

**Result**: Status lookups are O(1) regardless of the user's task history. No full table scan, no application-level filtering.

### 4c. Broker Lifecycle Management in FastAPI

**Situation**: The Taskiq broker was created as a module-level singleton but never explicitly started or stopped, causing "broker not started" errors during worker startup and resource leaks on shutdown.

**Task**: Ensure the broker has a managed lifecycle tied to the FastAPI app lifespan.

**Action**: Added `startup()`/`shutdown()` calls to the FastAPI lifespan context manager. The broker starts after DB initialization and stops before engine disposal. Added a startup validation test (`test_broker_lifecycle`) that verifies the broker transitions through `created -> started -> shutdown`.

**Result**: No more "broker not started" errors. Clean shutdown on app restart. The managed lifecycle pattern was documented in `docs/agent/patterns.md` for future async resource management.
