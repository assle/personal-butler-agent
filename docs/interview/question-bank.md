# Personal Butler Agent — Interview Question Bank

> 76+ questions across 8 categories, including 10 required project questions and 2 coding exercises.

---

## Required Project Questions (10)

### Q1: Describe the project in 2-3 minutes.

**Suggested answer**: Personal Butler Agent is an AI personal assistant backend for WeChat Work. It serves two fundamentally different interaction models through a single system: real-time conversational agents (sub-second LangGraph ReAct loops for private chat and group mention) and async long-form research (multi-minute PostgreSQL DAG with Taskiq workers). The architecture is scene-first: private chat, group mention, and scheduled webhook push each have dedicated agents with their own tool sets, preventing cross-scene capability leaks. The system uses SQLite for local dev, PostgreSQL for production (Alembic-managed), ChromaDB for vector search, and Redis only for research task queueing and circuit breaker state. Evaluation is deterministic: 24 cases across 12 categories produce real metrics (mean topic coverage 0.78, citation validity 0.94) rather than hardcoded scores.

### Q2: Why WeChat Work instead of a web or mobile frontend?

**Suggested answer**: WeChat Work is the dominant enterprise communication platform in China. Building a bot inside it eliminates the adoption friction of a separate app — users interact with the butler the same way they interact with colleagues. The intelligent robot URL callback mode provides a reliable inbound channel with built-in retry, dedup (msgid), and enterprise-grade encryption. The group webhook system handles outbound push (scheduled messages, reminders, poll results). Custom-application API handles private delivery (research reports). Three independent channels, each owned by WeChat's infrastructure.

### Q3: What were the key architecture decisions?

**Suggested answer**: Seven key decisions: (1) Scene-specific agents over a global intent router — clearer boundaries, easier to test, safer. (2) LangGraph StateGraph for interactive agents, PostgreSQL DAG for research — matching execution model to workload. (3) PostgreSQL authoritative, Redis transport — DB owns state, queue carries only task IDs. (4) SQLite dev, PostgreSQL prod — zero-config dev without sacrificing production schema management via Alembic. (5) Embedding API with local hash fallback — never crash on API failure. (6) Dynamic tools default-denied — every tool explicitly reviewed before LLM planners can use it. (7) Delivery separate from execution — preserved reports on delivery failure, no cascading failures.

### Q4: Why LangGraph for scene agents but not for the research pipeline?

**Suggested answer**: Different execution models. Scene agents need low-latency, single-invocation loops: user message enters, agent reasons, calls tools, replies — all in under 3 seconds. LangGraph StateGraph + MemorySaver is purpose-built for this. Research runs take minutes, span process boundaries (FastAPI -> Redis -> Worker), and need durability across worker restarts. PostgreSQL rows with leases provide atomic state transitions, lease recovery, and retry policies that LangGraph's in-memory checkpointer cannot. The research pipeline treats each step as a first-class DB record — not a graph node — because you need database-level guarantees when steps can take 30+ seconds and workers can crash mid-step.

### Q5: How does the system handle reliability?

**Suggested answer**: Three layers. First, typed failure classification: every step failure is categorized (timeout, rate_limited, execution_error) with per-category retry policy (exponential backoff, max retries, per-source parameters). Second, Redis circuit breaker: opens after configurable consecutive failures per circuit key, prevents cascading failures when a provider is degraded. Third, lease watchdog: workers claim steps with PostgreSQL row-level locks and a lease timestamp. If a worker crashes, the lease expires and another worker recovers the step using an atomic `UPDATE ... WHERE status='running' AND lease_expires_at < NOW()`, eliminating the TOCTOU race of release-then-claim. The quality gate provides a fourth layer for output correctness: bounded repair retries when the LLM produces claims without evidence backing.

### Q6: How do you evaluate quality?

**Suggested answer**: Two orthogonal dimensions. Quality evaluation: 24 predefined cases across 12 categories (comparison, performance, architecture, factual, howto, troubleshooting, design, security, best-practice, migration, research, data-modeling). Each case runs through the offline fixture evaluator (no DeepSeek calls) and computes four deterministic metrics: topic coverage, citation validity, required source coverage, and unsupported material claim rate. Mean scores: coverage 0.78, citation validity 0.94, source coverage 0.99, unsupported rate 0.06. Benchmark evaluation: worker-count tests (1/3/5 workers) in a PostgreSQL controlled harness measure throughput and latency under normal, timeout, execution_error, and rate_limited scenarios.

### Q7: How do you prevent security issues like SSRF and prompt injection?

**Suggested answer**: SSRF: the URL security policy (`src/research/web/url_policy.py`) validates all outbound URLs against a blocklist and allowlist before fetching. Internal IP ranges (10.x, 172.16-31.x, 192.168.x, 127.x) are blocked by default. Prompt injection: the governed tool registry (`ResearchToolRegistry`) enforces a 5-rule permission chain — system admin, workspace admin, workspace permission, tool policy, default denied. Permission decision occurs when `ResearchToolRegistry.execute()` runs — tools without an explicit permission rule are denied at execution time by the PermissionEngine. The LLM planner never has direct access to system tools; it can only call registered, permission-checked research tools. Additionally, the tool gate provides a deterministic check that prevents LDAP-style injection from bypassing the registry.

### Q8: What would you improve next?

**Suggested answer**: Four priorities. (1) MCP provider integration — the provider boundary is defined but the transport layer is not implemented; adding stdio/SSE MCP transport would allow dynamic tool discovery from external servers. (2) Online evaluation — current evaluation is offline (predefined cases); an online eval loop would measure production performance with real user queries. (3) Multi-user conversation memory — current memory is per-user SQLite; scaling to 100+ users with shared knowledge requires PostgreSQL-backed conversation memory with proper indexing. (4) CI completion — the CI pipeline is in place but not yet proven green end-to-end; live E2E testing with actual DeepSeek calls remains future work.

### Q9: What was the biggest engineering challenge?

**Suggested answer**: The lease recovery race condition. The original two-step recovery (release lease, then claim) created a window where a parallel worker could steal the step. Fixing this required making the state transition atomic at the database level — a single `UPDATE ... SET status='ready', lease_expires_at=NULL WHERE status='running' AND lease_expires_at < NOW()`. This seems obvious in retrospect, but it's a classic distributed systems bug that only manifests under concurrent worker load. The fix taught me to think in terms of database transactions rather than code sequences when designing multi-worker systems.

### Q10: How would you scale this to support 1000 users?

**Suggested answer**: The foundation is already in place. PostgreSQL migration is done (Alembic-managed). Workspace governance isolates data per team. The Taskiq worker pool separates research execution from HTTP serving. To reach 1000 users: (1) Connection pooling for PostgreSQL — current implementation opens per-request connections; PgBouncer or SQLAlchemy pool pre-configure. (2) Read replicas for ChromaDB — vector search is read-heavy; separating write and read paths reduces contention. (3) Taskiq worker auto-scaling — current max_async_tasks and --workers are static; dynamic scaling based on queue depth would handle load spikes. (4) Conversation memory indexing — current per-user message table needs composite indexes on (user_id, created_at) for efficient range queries at scale. (5) Rate limiting per workspace — prevent a noisy workspace from starving others.

---

## Category 1: Architecture & Design (10 questions)

### Q11: Why scene-specific agents instead of a global intent router?

**Suggested answer**: Three reasons: safety (group chat cannot accidentally access private-chat-only tools like training), testability (each scene agent has focused tests), and clarity (scene dispatch happens before LLM invocation, making the routing logic deterministic and auditable). A global intent router would merge these boundaries, making it harder to reason about which capabilities are available in which context.

### Q12: How does scene dispatch work?

**Suggested answer**: The callback router normalizes the incoming WeChat Work message to an `InboundMessage`. `dispatch_message()` checks `chat_type`: for `single`, it routes directly to `PrivateButlerAgent.handle()`. For `group`, it calls `apply_group_policy()` first, which saves the message, classifies the trigger via keyword matching (summarize, weather, poll, translate, simple_qa), and passes the category to `GroupMentionAgent.handle()` — the agent never re-classifies unless called directly.

### Q13: Why both SQLite and PostgreSQL? Why not just one?

**Suggested answer**: SQLite provides zero-config development: `uv run uvicorn` with no external dependencies. PostgreSQL provides production-grade concurrency, proper schema migrations via Alembic, and tsvector full-text search. The SQLAlchemy ORM abstracts the difference, so the application code is database-agnostic. The migration from SQLite to PostgreSQL is handled by Alembic migration scripts, and a CLI command (`butler-migrate-sqlite-to-postgres`) handles data migration.

### Q14: How does the architecture handle feature flags?

**Suggested answer**: Via environment variables and conditional wiring in `main.py`. Research is gated by `RESEARCH_ENABLED=true` — without it, the broker, queue, and workers are never initialized. Web search defaults to disabled (`WEB_SEARCH_ENABLED=false`). DashScope embedding is gated by `DASHSCOPE_API_KEY`. This keeps the base startup zero-dependency while allowing optional features to be enabled.

### Q15: How do you handle the broker lifecycle?

**Suggested answer**: The Taskiq broker (`src/research/broker.py`) is managed by the FastAPI lifespan context manager: `broker.startup()` runs after DB initialization, `broker.shutdown()` runs before engine disposal. This ensures clean startup/shutdown and prevents "broker not started" errors. Worker processes start separately with `taskiq worker src.research.broker:broker src.research.tasks`.

### Q16: Why a shared utility for translation instead of a dedicated agent?

**Suggested answer**: Translation is a single LLM call — "translate X to Y". Creating a full agent (state + nodes + graph + handle) for this would be excessive ceremony. The shared utility pattern (`src/agents/translate.py`) is simpler and is called both as a LangChain tool (private chat) and as a graph node (group mention). The rule: shared utility for single-step LLM calls, domain agent for multi-step workflows with state and persistence.

### Q17: How do you prevent circular dependencies between agents?

**Suggested answer**: Agent dependencies are hierarchical and unidirectional: scene agents depend on domain agents, domain agents depend on services (LLM, DB, knowledge), services depend on nothing. No agent depends on another agent. Domain agents (`SummaryAgent`, `ReminderAgent`, `PollAgent`) are invoked as tools by scene agents, not as independent agents with their own routes. This keeps the dependency graph acyclic and testable.

### Q18: Why LangGraph over a simpler function-calling loop?

**Suggested answer**: LangGraph StateGraph provides three things a manual loop doesn't: first-class state machine with conditional routing (nodes + edges separate from logic), built-in checkpointing via MemorySaver for multi-turn conversation memory, and tool integration through ToolNode (automatic tool message handling, parallel tool execution, error propagation). For simple linear workflows, a manual loop is fine. For ReAct agents with conditional routing and checkpointing, LangGraph saves significant custom boilerplate.

### Q19: How does the system handle conversation memory across multiple turns?

**Suggested answer**: Six-turn (12-message) sliding window with LLM-compressed summary. The recent 12 messages stay in the prompt in full fidelity. When a user exceeds 24 total messages, the oldest 12 are compressed into a single summary string by a lightweight LLM call. Both summaries and recent messages persist to SQLite, surviving process restarts. This differs from LangGraph's in-memory MemorySaver, which is only for single-session graph checkpointing.

### Q20: Why separate delivery from research execution?

**Suggested answer**: Isolation prevents cascading failures. If delivery fails (WeChat API transient error), the completed report is preserved in PostgreSQL and can be re-delivered. If research fails, delivery is never enqueued. Two independent Taskiq tasks ensure that failure in one does not affect the other. The trade-off is an additional async hop, but for research that takes minutes of LLM time, the extra seconds are negligible.

---

## Category 2: Agent & LLM (10 questions)

### Q21: How does PrivateButlerAgent route requests?

**Suggested answer**: First, regex checks for hardcoded patterns: "深度研究：" goes to the research submission service, "查看研究任务" goes to status lookup. Second, regex check for reminder intents bypasses LLM entirely. Third, the LangGraph ReAct loop: call_model -> tools_condition -> (ToolNode | extract_reply). The model receives conversation context, user profile, and tool descriptions, then either calls a tool or produces a final reply.

### Q22: What are the 15 tools available to PrivateButlerAgent?

**Suggested answer**: Summarize text, summarize group chat, search local knowledge, add to knowledge, search web, query weather, create group webhook reminder, list reminders, cancel reminder, translate, add memory, list memories, update memory, delete memory, search memory.

### Q23: How do tools get runtime context (user_id, db session)?

**Suggested answer**: Tools read context from `langgraph.config.get_config()` at runtime, not from LLM-provided parameters. This prevents prompt injection from fabricating user IDs or DB sessions. The context is injected by the scene agent's handle() method before invoking the graph.

### Q24: How does the group mention agent classify triggers?

**Suggested answer**: `apply_group_policy()` does keyword matching before any LLM call: "总结"/"摘要" -> summarize_group, "天气" -> weather, "投票"/"创建投票" -> poll, "翻译" -> translate, "?"/"什么"/"如何" -> simple_qa. If none match and the message is not a poll action, the agent does not reply. The matched category is passed to GroupMentionAgent, which routes to the appropriate node without re-classifying.

### Q25: What happens when the LLM returns a hallucinated tool call?

**Suggested answer**: LangChain ToolNode validates tool names and parameter schemas at runtime. Unknown tool names produce an error ToolMessage that the agent sees in the next reasoning step. Malformed parameters are caught by Pydantic validation. The agent can then correct its call or produce a text reply explaining the limitation. No invalid tool call ever reaches the actual tool implementation.

### Q26: How do you handle LLM rate limits?

**Suggested answer**: Two layers. The research pipeline has a Redis circuit breaker that opens after configurable consecutive failures (detected as `rate_limited` failure category). Once open, the circuit breaker blocks requests for the cooldown period before allowing a test request. The scene agent layer does not have rate limiting — under single-user usage, DeepSeek API rate limits are unlikely to be hit.

### Q27: Why DeepSeek through LangChain ChatOpenAI?

**Suggested answer**: LangChain ChatOpenAI provides a standard interface (chat, bind_tools, structured output) that integrates with LangGraph's ecosystem. The DeepSeek API is OpenAI-compatible, so `langchain_openai.ChatOpenAI` works with `base_url=https://api.deepseek.com` and `model=deepseek-chat`. This makes provider changes trivial — just update the base URL and model name.

### Q28: How does the Summarizer produce multi-turn conversation summaries?

**Suggested answer**: It does not produce multi-turn summaries — that's the ConversationMemory's role. The Summarizer (SummaryAgent) is a single-LLM-call tool that either summarizes a block of text the user provides, or summarizes recent group chat history. It is stateless and context-independent.

### Q29: How do you test LLM-dependent code without real API calls?

**Suggested answer**: Mocking at the LLMClient level. Tests set `DEEPSEEK_API_KEY=test` and patch `LLMClient.ainvoke()` or `ChatOpenAIMock` to return predefined responses. The mock preserves the LangChain message interface, so agent code passes through unchanged. Integration tests run against DeepSeek with isolated databases when an API key is configured. The evaluation framework (24 cases) runs offline against fixture data with no DeepSeek calls.

### Q30: How does the system handle context window limits for long conversations?

**Suggested answer**: The sliding window keeps only the most recent 12 messages in context (6 turns). The LLM-compressed summary captures earlier key facts in a single sentence. Research reports are delivered asynchronously via custom-app API, bypassing the chat context entirely. For knowledge retrieval, only top-k chunks (configurable, default 5 after reranking) are injected into the prompt.

---

## Category 3: Database & Storage (10 questions)

### Q31: Explain the database migration strategy.

**Suggested answer**: Alembic owns all DDL. `Base.metadata.create_all` is a dev-only fallback. When `DATABASE_REQUIRE_MIGRATIONS=true` (production default), startup verifies the alembic revision is at HEAD. Migration scripts in `alembic/versions/` are ordered, replayable, and reviewed. SQLite dev uses `DATABASE_REQUIRE_MIGRATIONS=false` to skip the check.

### Q32: How do you handle concurrent writes with SQLite?

**Suggested answer**: SQLite serializes writes — only one writer at a time. Under single-user usage this is fine. When research workers (Taskiq) run concurrently with the FastAPI app, each opens its own session, and SQLite's WAL mode allows concurrent reads. PostgreSQL migration is the production solution for multi-user concurrency.

### Q33: Why ChromaDB instead of pgvector or Pinecone?

**Suggested answer**: ChromaDB is embedded (no external server), zero-config (single directory), and sufficient for personal-scale vector search (tens of thousands of chunks). pgvector would require PostgreSQL extension installation. Pinecone would require a cloud API key. ChromaDB fits the project's "local-first, zero-infrastructure-dependency" philosophy.

### Q34: How does workspace isolation work at the database level?

**Suggested answer**: Every research task has an immutable `workspace_id`. Service-layer queries filter by workspace_id in every SELECT/UPDATE. Cross-workspace access is prevented by application-level checks, not just DB constraints, because a malicious or buggy query could bypass DB-level row security. Workspace membership is resolved by `WorkspaceService`.

### Q35: How are database connections managed in the research worker processes?

**Suggested answer**: Each Taskiq worker process creates its own async SQLAlchemy engine on startup. Sessions are per-request (per-step). This avoids cross-process session conflicts and allows each worker to have independent connection pooling. The FastAPI app has its own engine, sharing only the database file (SQLite) or server (PostgreSQL).

### Q36: How do you prevent duplicate research tasks?

**Suggested answer**: Two dedup levels. (1) Per-user active task limit: one active task per user — submitting a new research request while one is running returns the existing task ID. (2) Source message ID dedup: `source_msgid` from the WeChat callback ensures the same user message cannot create multiple tasks. Both checks happen in `ResearchTaskService.create_task()` within a transaction.

### Q37: How does evidence deduplication work?

**Suggested answer**: SHA-256 hash of `(workspace_id, source_ref, excerpt)` produces a unique evidence key. Before inserting a new evidence record, the service checks for an existing record with the same hash. This prevents duplicate evidence from multiple specialist invocations on the same source.

### Q38: Why Redis for circuit breaker state instead of PostgreSQL?

**Suggested answer**: Redis provides fast key expiration (TTL), which maps naturally to circuit breaker cooldown periods. The `SET key value EX seconds NX` pattern handles concurrent worker access safely. PostgreSQL would require a background cleanup job for expired circuit state. Redis is already present for the Taskiq queue, so no additional infrastructure is needed.

### Q39: How do you handle database migrations for the ChromaDB vector store?

**Suggested answer**: ChromaDB collections are versioned by collection name. When the embedding dimension changes (e.g., upgrading the embedding model), a new collection is created and data is re-indexed. A CLI command (`butler-migrate-to-chroma`) handles data migration from the old vector format. ChromaDB stores its data in `chroma_data/` directory, which is gitignored.

### Q40: What indexes exist on the research_tasks table?

**Suggested answer**: Primary index on `task_id` (UUID, PK). Secondary indexes on `(user_id, status)` for per-user status lookups, `status` for worker polling, and `workspace_id` for isolation queries. The ORM model in `src/models/research.py` defines these via SQLAlchemy `Index` declarations.

---

## Category 4: Testing & Quality (10 questions)

### Q41: How is the codebase tested?

**Suggested answer**: Three layers. Unit tests (fast, mock LLM, isolate DB) cover agent logic, service methods, and utility functions. Integration tests exercise the full pipeline against real PostgreSQL and Redis in CI. Evaluation tests (24 cases) run offline against fixture data — no DeepSeek calls, deterministic metric computation. CI runs both unit and integration tests on every push and PR.

### Q42: What does the CI pipeline look like?

**Suggested answer**: Two jobs in `.github/workflows/test.yml`. Unit job: checkout, uv sync, pytest (excluding integration/smoke), compileall check, CLAUDE.md/AGENTS.md sync check. Integration job: PostgreSQL 16 + Redis 7 service containers, Alembic upgrade, integration tests.

### Q43: How do you ensure deterministic quality measurement?

**Suggested answer**: The evaluation framework defines 24 cases with structured fixture inputs. Metrics are computed from offline analysis of the fixture artifacts: topic coverage (sub-topics addressed), citation validity (citations support claims), required source coverage (required sources cited), and unsupported claim rate (claims without evidence). These are exact, reproducible calculations — not LLM-judged scores, and no actual DeepSeek calls are made.

### Q44: How do you test idempotent behavior?

**Suggested answer**: `callback_inbox.py` writes `inbound_messages` by msgid with a UNIQUE constraint. Tests send the same message twice and verify the second insertion is ignored (ON CONFLICT DO NOTHING). Similarly, research task creation by `source_msgid` is tested for duplicate submission idempotency.

### Q45: How do you test the quality gate?

**Suggested answer**: The quality gate test (`test_research_quality_gate.py`) creates a report with missing evidence bindings, runs the gate, and verifies it fails. Then runs the repair coordinator and verifies the gate passes after bounded repair. The citation reviewer test sends a report with claims that have contradictory evidence and verifies the findings.

### Q46: How do you test lease recovery?

**Suggested answer**: The watchdog test starts a step with a short lease (e.g., 10ms), waits for expiry, then verifies the step transitions from `running` to `pending` via the atomic recovery query. A second test verifies that a non-expired lease is not recovered. A third test with parallel worker simulation verifies no race condition.

### Q47: How are mock objects structured?

**Suggested answer**: `LLMClient` is mocked at the LangChain level: `MockChatOpenAI` returns predefined `AIMessage` responses with optional tool_calls. Database mocking uses `pytest` fixtures that create an in-memory SQLite engine and session per test function. External services (weather, search, WeChat API) are mocked with `unittest.mock.patch` or `httpx_mock`.

### Q48: How do you prevent CLAUDE.md and AGENTS.md from drifting?

**Suggested answer**: The CI pipeline has a `cmp -s CLAUDE.md AGENTS.md` check that fails the build if they differ. The update workflow in CLAUDE.md specifies: "Modified CLAUDE.md -> Copy to AGENTS.md to keep them byte-for-byte identical."

### Q49: What code quality checks exist?

**Suggested answer**: CI runs `uv run python -m compileall -q src tests` to catch syntax errors and import issues. The `cmp -s CLAUDE.md AGENTS.md` check prevents documentation drift. Ruff/black checks are not yet in CI but are planned. Pre-commit hooks are not used to keep setup minimal.

### Q50: How do you test the research pipeline without real LLM calls?

**Suggested answer**: Integration tests for the pipeline mock at the step executor level, returning predefined evidence and claim structures. Unit tests for individual components (supervisor, specialist, synthesizer, reviewer) mock the LLM to return structured output matching the expected schema. The end-to-end evaluation runner is the only component that calls the real LLM.

---

## Category 5: Async & Distributed Systems (10 questions)

### Q51: How does the Taskiq workflow work end-to-end?

**Suggested answer**: FastAPI producer: submission creates a DB task record and calls `run_research_task.kiq(task_id)`, which pushes the task_id to a Redis Stream. Worker: `taskiq worker` process polls the Redis Stream, deserializes the task_id, opens a DB session, loads the task, and executes the pipeline (plan -> steps -> synthesize -> review -> quality gate -> delivery). Delivery is a separate Taskiq task: after completing the report, the worker enqueues a delivery task that calls the WeChat custom-app API.

### Q52: How does Redis Stream handle message loss?

**Suggested answer**: By default, Redis Streams with `ack-type when_executed` ensure that a message is not removed from the stream until the worker explicitly acknowledges it. If a worker crashes mid-processing, the message remains in the PEL (Pending Entry List) and can be re-dispatched to another worker after a timeout. This provides at-least-once delivery.

### Q53: How do you prevent multiple workers from processing the same step?

**Suggested answer**: Steps use PostgreSQL row-level locking (`SELECT ... FOR UPDATE SKIP LOCKED`) when claiming. The claim query: `UPDATE research_steps SET status='running', lease_expires_at=NOW()+interval WHERE status='ready' AND step_id=? RETURNING step_id`. Workers only select steps in `ready` status (the dispatcher transitions steps from `pending` to `ready` after dependency resolution). If two workers race, only one gets the RETURNING row. The other's UPDATE affects zero rows.

### Q54: What happens when a worker crashes mid-step?

**Suggested answer**: The lease expires (configurable TTL). The watchdog in each worker's recovery loop runs periodically: `UPDATE research_steps SET status='ready', lease_expires_at=NULL WHERE status='running' AND lease_expires_at < NOW()`. The recovered step (now `ready`) can then be claimed by any available worker.

### Q55: How do you handle step dependencies in a distributed setting?

**Suggested answer**: The dispatcher uses a `NOT EXISTS` subquery pattern: `SELECT * FROM research_steps WHERE status IN ('pending', 'ready') AND NOT EXISTS (SELECT 1 FROM research_step_deps WHERE step_id=research_steps.step_id AND dep_status != 'completed')`. This makes the dependency check atomic at query time — no race between checking dependencies and claiming a step. Steps transition from `pending` to `ready` only after all dependencies are resolved; workers then claim `ready` steps.

### Q56: Why Taskiq over Celery?

**Suggested answer**: Taskiq is async-native — the broker, worker, and task definitions are all async. Celery requires sync wrappers around async code. Taskiq has fewer configuration files (no celery.py, no beat_schedule config). Integration with existing async SQLAlchemy sessions is clean. The Redis Stream backend provides reliable at-least-once delivery.

### Q57: How does the approval flow work?

**Suggested answer**: The supervisor produces a PlanDraft, which must pass through approval before execution. `ApprovalPolicy` evaluates the plan against workspace rules: first-use requires explicit approval; high-cost plans (>budget) require approval. The approval happens in the FastAPI process (callback handler), not the worker, because it needs the workspace context. Once approved, the plan's steps become eligible for dispatch.

### Q58: How do you debug distributed research failures?

**Suggested answer**: The observability system (`src/research/observability.py`) injects a trace context (trace_id) at every stage: submission, planning, each step execution, synthesis, review, delivery. Logs include stage timing, LLM call duration, and failure details. The operator can query the research_steps table directly to see which step last touched a given task. (Note: full distributed trace with per-span correlation across processes is not implemented — inter-process correlation relies on the shared trace_id in log lines.)

### Q59: How does the system handle SQLite write contention with multiple workers?

**Suggested answer**: SQLite WAL mode allows concurrent reads but serializes writes. Under 1-3 research workers + 1 FastAPI process, write contention is manageable because steps are short-lived (seconds, not minutes). The timeout scenario (5s simulated delay) shows the impact: throughput drops to 0.2 t/s per worker because each write waits for the previous to complete. PostgreSQL migration resolves this for production.

### Q60: How do you ensure delivery workers only run after the report is complete?

**Suggested answer**: Delivery is a separate Taskiq task enqueued by the research worker only after `ResearchTaskService.complete_with_report()` succeeds. The delivery task reads the completed report from PostgreSQL and calls the WeChat API. If the research worker crashes between completing the report and enqueuing delivery, a recovery worker can re-enqueue delivery on startup by scanning for completed reports with pending deliveries.

---

## Category 6: Research Pipeline (10 questions)

### Q61: What are the phases of the research pipeline?

**Suggested answer**: Phase 1: PostgreSQL + workspace governance + Alembic. Phase 2: DAG steps + approval + budget. Phase 3: Structured supervisor planner + specialists + governed tool registry + evidence persistence. Phase 4: Quality gate + citation review + bounded repair. Phase 5: Retry + circuit breaker + lease watchdog + SSRF protection. Phase 6: Skills + evaluation framework + CI + observability. Phase 7: Worker benchmarks (1/3/5 workers, PostgreSQL controlled harness).

### Q62: How does the supervisor produce a plan?

**Suggested answer**: The supervisor receives the user's research query and available skill manifests. It calls `ainvoke_structured()` with a Pydantic `PlanDraft` schema, producing a validated JSON plan with typed steps, tool names, input payloads, and explicit dependencies. The supervisor never searches the web or KB during planning — retrieval is declared as explicit steps to be executed by specialists.

### Q63: What information is in a research skill manifest?

**Suggested answer**: A ResearchSkillManifest (YAML frontmatter in `research_skills/*/SKILL.md`) declares: skill name and description, required tools (knowledge search, web search, LLM completion), allowed source types, budget parameters, and prompt templates. Skills are directory-scanned and loaded by name via `ResearchSkillCatalog` and `ResearchSkillLoader`.

### Q64: How does the quality gate make decisions?

**Suggested answer**: The gate is deterministic: it checks each ResearchClaim for required evidence bindings. If a material claim has zero evidence records or has unresolved error findings from the reviewer, the gate fails. The repair coordinator then has bounded rounds (configurable max_rounds + token budget) to re-synthesize specific claims. If repair is exhausted, escalation is explicit — the report is marked for manual review.

### Q65: How does the reviewer validate citations?

**Suggested answer**: The reviewer receives only claims and their bound evidence — not the full report or raw LLM output. This prevents the reviewer from being biased by the synthesis context. For each claim, the reviewer checks (via a separate LLM call): does the cited evidence actually support the claim text? Findings are structured: `claim_id`, `finding_type` (valid/invalid/unsupported), and `rationale`.

### Q66: How does the system handle budget tracking?

**Suggested answer**: Each plan has a `max_budget_microunits` from the skill manifest. After every step execution, the executor checks the cumulative cost against the budget. If exceeded, remaining steps are marked `cancelled` and the task transitions to `budget_exceeded` status. The supervisor could re-plan with reduced scope, but this is not yet implemented.

### Q67: What happens when a specialist tool call fails?

**Suggested answer**: The step executor catches the failure, categorizes it (timeout, rate_limited, execution_error), and applies the retry policy. The step status remains `running` during retry. After exhausting retries, the step is marked `failed` and dependent steps are blocked. The task status becomes `failed`.

### Q68: How are research steps stored in the database?

**Suggested answer**: Each step is a row in `research_steps` with: `step_id` (UUID), `task_id` (FK), `step_index`, `status` (pending/ready/running/completed/failed/cancelled), `tool_name`, `input_payload` (JSON), `output_summary`, `lease_expires_at`, `attempts`, `last_error`, `worker_id`, and timestamps. Dependencies are in `research_step_deps` as (step_id, dep_step_id) pairs.

### Q69: How does the research pipeline handle task cancellation?

**Suggested answer**: There is no explicit cancel API for running research. The primary mechanism is the active-task-per-user limit — submitting a new task while one is running returns the existing task ID. A future improvement would add a cancel endpoint that transitions running steps to `cancelled` status and the task to `cancelled`.

### Q70: How does the research submission handle the 30-minute WeChat response_url expiry?

**Suggested answer**: It doesn't. The research pipeline is explicitly designed around the limitation: the submission endpoint returns immediately ("研究任务已提交"), and delivery happens asynchronously via the custom-application API (which has no time limit). The `response_url` path is only used for passive reply to the initial submission.

---

## Category 7: Production & Operations (10 questions)

### Q71: How should a production deployment be configured?

**Suggested answer**: Four processes. (1) FastAPI behind a reverse proxy (nginx/Caddy) with HTTPS. (2) PostgreSQL 16+ with PgBouncer for connection pooling. (3) Redis 7+ for queue and circuit breaker. (4) Taskiq workers (1-3 processes, `--workers 3 --max-async-tasks 4`). All behind WeChat Work's IP allowlist. Configured via `.env` with `DATABASE_URL=postgresql+asyncpg://...`, `REDIS_URL=redis://...`, `RESEARCH_ENABLED=true`, `DATABASE_REQUIRE_MIGRATIONS=true`.

### Q72: How do you monitor the system?

**Suggested answer**: Currently minimal. PostgreSQL health via `pg_isready`. Redis health via `redis-cli ping`. Alembic version check via `alembic check`. Queue depth via `XLEN butler-research`. Circuit breaker state via `KEYS research:circuit:*`. Trace logging provides per-request observability. No external monitoring system (Datadog/Grafana) is integrated.

### Q73: How do you handle secrets management?

**Suggested answer**: `.env` file for local development (gitignored). For production, environment variables injected by the deployment platform. Key secrets: `DEEPSEEK_API_KEY`, `WECOM_AIBOT_TOKEN`, `WECOM_AIBOT_ENCODING_AES_KEY`, `WECOM_APP_SECRET`. The deploy guide (deployment.en.md) documents required variables. No secrets are committed to the repository.

### Q74: What is the on-call runbook for the research pipeline?

**Suggested answer**: Documented in `docs/operations/research-runbook.md`. Three common scenarios: stuck steps (watchdog auto-recovers), open circuit (check Redis keys, circuit auto-resets after cooldown), approval backlog (check tasks in `awaiting_approval` status). For severe failures: kill all workers, drain Redis queue, fix the issue, restart workers.

### Q75: How do you handle idempotent delivery to WeChat?

**Suggested answer**: The `research_deliveries` table tracks delivery status per task. Before sending, the delivery service checks for an existing `sent` record. If found, delivery is skipped. The WeChat API itself does not provide idempotency guarantees, so DB-level tracking is the safety net.

### Q76: What backup strategy exists?

**Suggested answer**: SQLite/PostgreSQL backups handled by the hosting provider or cron job. ChromaDB is a directory (`chroma_data/`) that can be backed up like any file store. No automated backup system is integrated into the project — it relies on the deployment platform's backup capabilities.

### Q77: How would you add health check endpoints?

**Suggested answer**: Add a `/health` endpoint that checks PostgreSQL connectivity (SELECT 1), Redis connectivity (PING), ChromaDB collection count, and Alembic migration status. The endpoint returns HTTP 200 if all checks pass, 503 if critical checks fail. This endpoint would be used by the reverse proxy's health check and the container orchestrator.

### Q78: How do you handle log aggregation across processes?

**Suggested answer**: Currently no centralized log aggregation. Each process (FastAPI, N workers) logs to stdout/stderr. Trace IDs (trace_id) are injected into every log line, allowing manual correlation across processes. Span IDs are not implemented, so inter-process correlation relies on the shared trace_id. For production, deploying with systemd or Docker Compose and aggregating with Loki/Promtail would be the standard approach.

### Q79: How do you manage worker scaling?

**Suggested answer**: Manually, via `--workers N`. The controlled-harness benchmark results (PostgreSQL, 1/3/5 workers, 12 tasks) guide the choice. The optimal worker count depends on workload mix (normal vs timeout-heavy) and database contention. Dynamic scaling based on queue depth is future work.

### Q80: How does the system degrade when Redis is unavailable?

**Suggested answer**: If `RESEARCH_ENABLED=true` but Redis is down, the broker startup fails and the FastAPI lifespan logs an error. The app continues to serve non-research requests. If Redis becomes unavailable mid-operation, enqueue operations fail with an exception that is caught at the submission endpoint, returning an error message. The expected production setup runs Redis on the same VPC as the app, making Redis outages rare.

---

## Category 8: General Engineering (6 questions)

### Q81: How do you handle Python version compatibility?

**Suggested answer**: The project requires Python 3.13+ and uses `uv` for dependency management. The `pyproject.toml` specifies `requires-python = ">=3.13"`. CI runs on ubuntu-latest with the astral-sh/setup-uv action. No polyfills or compatibility shims are used. The async SQLAlchemy pattern requires Python 3.13+ for full asyncio support.

### Q82: What is the project's dependency management philosophy?

**Suggested answer**: Minimal dependencies with clear purpose. `uv` for package management (fast, deterministic). Core: FastAPI (web), LangGraph+LangChain (agent), SQLAlchemy+aiosqlite/asyncpg (DB), ChromaDB (vectors), Taskiq+Redis (queue), APScheduler (cron), Pydantic (validation). Each dependency has a specific role and no unnecessary abstraction layers. Dev dependencies (pytest, ipykernel) are in optional `dev` extra.

### Q83: How do you ensure code consistency?

**Suggested answer**: Project-level CLAUDE.md and AGENTS.md provide consistent guidance to AI coding tools. The `docs/agent/` directory documents patterns, decisions, and troubleshooting. Code review focuses on structural consistency: agents follow the `state.py + nodes.py + graph.py + handle()` pattern, service classes follow the CRUD pattern, all functions have Chinese documentation comments.

### Q84: How do you balance Chinese and English documentation?

**Suggested answer**: Code comments are in Chinese for the target audience (Chinese-speaking developers maintaining the project). User-facing documentation exists in both Chinese (README.md, deployment.md) and English (README.en.md, deployment.en.md). Architecture decisions and interview docs are in English for broader accessibility. The codebase uses English identifiers for Python standard compatibility.

### Q85: What is the git workflow?

**Suggested answer**: Feature branches with descriptive names. Commits follow conventional commit style (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`). PRs are reviewed before merge to main. No force pushes to main. The CLAUDE.md documents this workflow. No automated changelog generation — commit history serves as the changelog.

### Q86: How do you handle dependency version pinning?

**Suggested answer**: `uv.lock` pins all dependencies transitively. `pyproject.toml` specifies minimum versions with `>=` constraints. This balances reproducibility (lock file) with flexibility (no upper bounds that would prevent security patches). Dependencies are updated via `uv sync --upgrade <package>` and reviewed before committing the updated lock file.

---

## Coding Exercises

### Coding Exercise 1: Exponential Backoff Retry

Implement a function `retry_with_backoff` that:
1. Accepts an async callable `fn`, `max_retries: int`, `base_delay: float`, and `max_delay: float`
2. Executes `fn()` and catches any exception
3. On failure, waits `base_delay * 2^attempt` seconds (capped at `max_delay`), then retries
4. After `max_retries` attempts, raises the last exception
5. Adds jitter (random 0-100ms) to each delay to prevent thundering herd

```python
import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> T:
    """
    Retry an async function with exponential backoff and jitter.

    Args:
        fn: Async callable to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds

    Returns:
        The result of the successful fn() call

    Raises:
        The last exception encountered after exhausting all retries
    """
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                jitter = random.uniform(0, 0.1)
                await asyncio.sleep(delay + jitter)

    raise last_exception  # type: ignore[misc]
```

### Coding Exercise 2: Idempotent Task Queue

Implement an in-memory idempotent task queue that:
1. Accepts tasks with a unique `task_id` (string)
2. If the same `task_id` is submitted twice, the second submission is silently ignored
3. `process_next()` dequeues and executes one task, returning the result
4. Tracks execution status: PENDING, RUNNING, COMPLETED, FAILED
5. `get_status(task_id)` returns the current status

```python
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import TypeVar

T = TypeVar("T")

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class IdempotentTaskQueue:
    """An idempotent task queue with status tracking."""

    def __init__(self) -> None:
        self._tasks: dict[str, tuple[Callable[[], Awaitable[T]], TaskStatus, T | Exception | None]] = {}

    def submit(self, task_id: str, fn: Callable[[], Awaitable[T]]) -> bool:
        """
        Submit a task. If task_id already exists, silently ignore.

        Returns:
            True if the task was newly added, False if it already existed.
        """
        if task_id in self._tasks:
            return False
        self._tasks[task_id] = (fn, TaskStatus.PENDING, None)
        return True

    async def process_next(self) -> str | None:
        """
        Process the next PENDING task (FIFO order).

        Returns:
            The task_id of the processed task, or None if no tasks are pending.
        """
        pending: list[str] = [
            tid for tid, (_, status, _) in self._tasks.items()
            if status == TaskStatus.PENDING
        ]
        if not pending:
            return None

        task_id = pending[0]
        fn, _, _ = self._tasks[task_id]
        self._tasks[task_id] = (fn, TaskStatus.RUNNING, None)

        try:
            result = await fn()
            self._tasks[task_id] = (fn, TaskStatus.COMPLETED, result)
        except Exception as e:
            self._tasks[task_id] = (fn, TaskStatus.FAILED, e)

        return task_id

    def get_status(self, task_id: str) -> TaskStatus | None:
        """Return the current status of a task, or None if not found."""
        entry = self._tasks.get(task_id)
        if entry is None:
            return None
        _, status, _ = entry
        return status

    def get_result(self, task_id: str) -> T | Exception | None:
        """Return the result or exception of a completed/failed task."""
        entry = self._tasks.get(task_id)
        if entry is None:
            return None
        _, _, result = entry
        return result
```
