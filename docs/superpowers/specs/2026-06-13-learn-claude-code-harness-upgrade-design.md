# Learn Claude Code-Inspired Research Harness Upgrade Design

## 1. Purpose

This design compares Personal Butler Agent with
`shareAI-lab/learn-claude-code` and defines a production-oriented upgrade for
small-team use.

The first delivery target is the existing private-chat deep research
capability. The design improves the runtime harness before extending the same
mechanisms to daily office automation or development workflows.

The target delivery window is six to eight weeks. The intended deployment is a
small internal team with multiple users and concurrent workers.

## 2. Selected Direction

The project will use a vertical-slice approach:

1. Upgrade the data and governance foundations needed by deep research.
2. Add a durable research task graph and a dynamically planning Supervisor.
3. Run internal knowledge and public web retrieval in parallel.
4. Bind report claims to evidence and enforce citation validation.
5. Add context management, recovery, budgets, and safety controls.
6. Expose stable Skill and tool-provider interfaces for later expansion.

This approach adopts the useful harness principles from Learn Claude Code
without copying coding-agent-specific Bash, worktree, filesystem mailbox, or
autonomous task-claiming mechanisms.

## 3. Comparison with Learn Claude Code

| Learn Claude Code mechanism | Current project | Upgrade decision |
|---|---|---|
| Stable agent loop and tool dispatch | LangGraph ToolNode loops exist in scene agents | Preserve LangGraph; add a research-specific tool registry |
| Permission pipeline | Scene restrictions and source scopes are distributed across modules | Add a centralized, policy-driven permission engine |
| Lifecycle hooks | Logging and side-path behavior are called directly | Add typed research lifecycle hooks |
| Todo and durable task graph | Research Phase 1 has one durable task, but no child-step DAG | Add persistent plans, steps, dependencies, leases, and retries |
| Context-isolated subagents | Phase 1 executes one LLM draft | Add isolated research specialists controlled by a Supervisor |
| On-demand skills | Prompts and policies are statically wired | Add a `ResearchSkill` catalog with on-demand content loading |
| Layered context compaction | Conversation memory uses a sliding window and summary | Add stage-specific context views and externalized large results |
| Memory selection and consolidation | Personalized memory fragments and profiles already exist | Reuse them through authorized gateways; do not duplicate memory |
| Runtime prompt assembly | Prompts are split by agent but mostly static | Assemble prompts from role, policy, skill, budget, and task context |
| Error recovery | Task timeout and limited delivery retry exist | Add classified retries, fallback, circuit breaking, and resume |
| Background tasks | Taskiq research and delivery workers already exist | Extend the existing queue instead of adding thread-based background jobs |
| Cron | APScheduler already supports reminders and pushes | Keep the existing scheduler; do not merge it into research execution |
| Agent teams and protocols | No research team protocol yet | Use typed database records and events rather than file mailboxes |
| Autonomous task claiming | Taskiq consumes whole research jobs | Add PostgreSQL step leasing with `SKIP LOCKED`, not free-form autonomy |
| MCP dynamic tools | No MCP runtime | Provide a governed tool-provider interface; defer broad MCP enablement |

The central lesson is to strengthen the model's operating environment:
well-described tools, constrained data access, clean context, durable state,
observable execution, and explicit permissions.

## 4. Scope

### 4.1 In Scope

- Private-chat research submission and status lookup remain the user entry.
- PostgreSQL becomes the authoritative structured database.
- Multiple workspaces and workspace-scoped authorization.
- A dynamic research Supervisor and specialist agents.
- Internal knowledge-base and public-web retrieval.
- Durable research plans, step dependencies, evidence, claims, and events.
- First-use and high-cost plan approval.
- Claim-level citation validation.
- Structured retries, budgets, timeouts, degradation, and recovery.
- Stable Research Skill and tool-provider extension interfaces.
- Enterprise WeChat custom-application report delivery.

### 4.2 Out of Scope

- General-purpose coding tools, shell access, and git worktree execution.
- Free-form peer debate or autonomous agent swarms.
- A universal plugin marketplace.
- Dynamic MCP tools receiving permission automatically.
- Group-chat research submission.
- An administration dashboard in the first release.
- Simultaneous production writes to SQLite and PostgreSQL.
- Storing hidden model reasoning or chain-of-thought.

## 5. Target Architecture

```text
Enterprise WeChat private callback
    -> PrivateButlerAgent
    -> BeforeResearch hooks
    -> identity, workspace, and baseline permission checks
    -> ResearchTaskService
    -> Redis Stream / Taskiq

Research workers
    -> Research Supervisor planning
    -> persistent Research Plan and Step DAG
    -> cost and policy evaluation
    -> optional plan approval
    -> Knowledge Researcher --------\
    -> Web Researcher ---------------+-> Evidence Store
                                      -> Synthesizer
                                      -> Citation Reviewer
                                      -> BeforeDelivery hooks
                                      -> Report Delivery Task
```

The database is authoritative. Redis transports task or step identifiers and
holds transient coordination data. Agent messages do not carry full source
documents, reports, or mutable permission scopes.

## 6. Harness Components

### 6.1 Research Supervisor

The Supervisor turns a question into a structured plan and dynamically selects
the required specialists. It owns orchestration decisions, but it does not
perform retrieval or write the final report.

It may append targeted steps after examining coverage gaps, subject to:

- maximum step count;
- maximum replanning count;
- token and monetary budgets;
- source and workspace permissions;
- hard execution timeout.

Every generated plan is validated before execution. Invalid dependencies,
cycles, unknown tools, or budget violations are rejected.

### 6.2 Specialist Agents

- **Planner capability**: identifies objectives, subquestions, evidence needs,
  dependencies, and expected cost.
- **Knowledge Researcher**: retrieves workspace-authorized public, user, and
  group knowledge through a constrained gateway.
- **Web Researcher**: searches and fetches public sources, returning structured
  evidence rather than prose conclusions.
- **Synthesizer**: writes claims only from persisted evidence.
- **Citation Reviewer**: independently validates claim support, source
  existence, citation placement, conflicts, and missing evidence.

Each specialist receives an isolated, minimum-necessary context and returns a
typed result. It cannot access another workspace or widen the task's source
scope.

### 6.3 Research Tool Registry

The registry exposes stable tool definitions with:

- name and structured input/output schemas;
- risk level;
- data scope;
- cost class;
- timeout;
- retry policy;
- approval requirements;
- provider identity and version.

The first built-in providers are knowledge search, public web search and fetch,
evidence extraction, synthesis, and citation validation.

### 6.4 Permission Engine

Permissions are evaluated independently from model intent.

| Operation | Default policy |
|---|---|
| Authorized internal knowledge read | Allow |
| Public web search and fetch | Allow with network safety checks |
| Workspace-scoped research writes | Allow and audit |
| First research use | Require approval |
| Estimated high-cost plan | Require approval |
| Budget-increasing replan | Require approval when policy threshold is crossed |
| Enterprise WeChat delivery | Allow only after delivery quality gate |
| Cross-workspace access | Deny |
| Unknown or unapproved dynamic tool | Deny |

The engine returns a structured decision: `allow`, `deny`, or
`require_approval`, plus the policy identifier and reason.

### 6.5 Hook Bus

Hooks add governance and observability without embedding them in each agent:

- `BeforeResearch`: resolve identity, workspace, permissions, and budgets.
- `AfterPlan`: validate DAG, cost, tools, and approval requirements.
- `BeforeTool`: validate scope, arguments, risk, and current budget.
- `AfterTool`: persist result references, timings, usage, and audit events.
- `OnError`: classify failure and choose retry, fallback, or terminal failure.
- `BeforeDelivery`: require a validated report and authorized recipient.
- `AfterResearch`: record terminal metrics and notification outcome.

Hooks cannot override an explicit deny. Hook failures use fail-closed behavior
for permissions and delivery, and fail-open behavior only for non-critical
metrics.

### 6.6 Task DAG Service

The service manages durable research steps and dependencies. It supports:

- DAG validation and cycle rejection;
- step readiness checks;
- atomic claims;
- leases and heartbeat renewal;
- retry counters and delayed retry;
- cancellation;
- timeouts;
- idempotency keys;
- dependency unblocking;
- parent-task status derivation.

Workers claim ready steps with PostgreSQL row locking:

```sql
SELECT ...
FOR UPDATE SKIP LOCKED
```

A lease expiry returns an unfinished step to the ready pool. Tool output writes
use idempotency keys so a retried worker does not duplicate evidence or reports.

### 6.7 Research Event Store

An append-only event table records:

- submission and approval;
- plan creation and validation;
- state transitions;
- tool invocation summaries and result references;
- retries, fallback, degradation, and cancellation;
- report validation;
- delivery attempts.

Events store structured decisions and references, not hidden model reasoning.
Secrets, access tokens, full sensitive payloads, and unnecessary personal data
are excluded or redacted.

## 7. Research Execution Flow

1. A user submits `深度研究：<问题>` in private chat.
2. The system resolves the user, workspace, role, and source permissions.
3. A durable task is created using the callback `msgid` as an idempotency key.
4. The Supervisor produces a typed plan with subquestions, dependencies,
   sources, tools, completion criteria, and estimated cost.
5. First-use or high-cost plans enter `awaiting_approval`; ordinary plans run
   automatically. Planning cannot invoke retrieval or other external tools.
6. After approval when required, the Task DAG Service activates validated
   steps.
7. Independent knowledge and web steps run concurrently when their dependencies
   are satisfied.
8. Each result is normalized into evidence with provenance and a content hash.
9. The Supervisor evaluates coverage and may add bounded follow-up steps.
10. The Synthesizer creates a draft with explicit claim-evidence bindings.
11. The Citation Reviewer validates every material claim.
12. Unsupported claims trigger bounded supplementary retrieval or removal.
13. A validated report is persisted and separately queued for delivery.
14. Delivery retries do not rerun research.

### 7.1 Task State

```text
submitted
  -> planning
  -> awaiting_approval
  -> running
  -> synthesizing
  -> validating
  -> completed
  -> delivering
  -> delivered

Any active state -> retrying | failed | cancelled
planning -> running
awaiting_approval -> running | cancelled
validating -> running | synthesizing
```

Terminal-state transitions are guarded by compare-and-set updates so duplicate
workers cannot complete or deliver the same task twice.

## 8. PostgreSQL Data Architecture

PostgreSQL replaces SQLite as the authoritative structured database for team
deployment. ChromaDB remains the embedded vector index initially, with vector
metadata referring to PostgreSQL document and chunk identifiers.

### 8.1 Core Tables

- `workspaces`: team boundary and policy configuration.
- `workspace_members`: users, roles, and membership status.
- `research_tasks`: requester, workspace, budget, approval, access scope, and
  aggregate status.
- `research_plans`: versioned Supervisor plans and cost estimates.
- `research_steps`: DAG nodes, dependencies, status, owner, lease, retries,
  tool, and idempotency key.
- `research_evidence`: source metadata, excerpts, hashes, provenance, and
  confidence.
- `research_claims`: material report claims and validation status.
- `research_claim_evidence`: claim-evidence bindings and support classification.
- `research_approvals`: policy reason, approver, decision, and approved budget.
- `research_events`: append-only lifecycle and audit events.
- `research_usage`: model, tokens, searches, latency, and estimated cost.
- `research_reports`: draft, validated, final, version, and quality status.
- `research_deliveries`: recipient, attempts, WeChat response, and status.

Every workspace-owned row carries `workspace_id`. Repository queries require a
workspace scope, and database constraints preserve parent-child workspace
consistency where practical.

### 8.2 Migration Strategy

1. Add PostgreSQL configuration and Alembic migrations.
2. Make SQLAlchemy engine configuration database-URL driven.
3. Create a one-time SQLite-to-PostgreSQL migration command.
4. Migrate and validate row counts, unique constraints, foreign keys, and
   representative records.
5. Reconcile Chroma metadata with PostgreSQL identifiers.
6. Run a controlled cutover and stop production writes to SQLite.
7. Keep the SQLite file only as a read-only migration artifact until backup
   retention permits removal.

Long-term dual-write or dual-database runtime support is explicitly rejected.

## 9. Evidence and Citation Quality Gate

Every evidence record includes:

- source URL or internal document identifier;
- title, publisher or author, and publication time when available;
- retrieval time;
- exact supporting excerpt or structured internal passage;
- source type and workspace scope;
- content hash;
- query and research step that produced it.

Every material report claim must bind to one or more evidence records. The
Citation Reviewer checks:

- source availability;
- whether the excerpt supports the claim;
- whether the citation points to the correct evidence;
- unsupported extrapolation;
- conflicts and meaningful counterevidence;
- uncited material claims.

Claims that fail validation are supplemented, weakened, marked uncertain, or
removed. They cannot remain in the final report as verified facts.

## 10. Context Management

The project will not pass an ever-growing research transcript between agents.

- The Supervisor sees plan summaries, step states, evidence coverage, and
  budgets.
- A retrieval specialist sees only its assigned subquestion, permitted sources,
  and relevant prior evidence summaries.
- The Synthesizer sees normalized evidence and report requirements.
- The Reviewer sees claims and their bound evidence.
- Full pages, long tool outputs, and report bodies remain in persistent storage.
- Context contains stable identifiers, excerpts, and bounded summaries.

When a context approaches its budget:

1. Remove duplicate or superseded status messages.
2. Replace old tool output with evidence references.
3. Consolidate low-value evidence summaries.
4. Generate a stage summary only when deterministic reductions are insufficient.

This applies Learn Claude Code's "cheap compaction first" principle while
preserving claim-level evidence.

## 11. Reliability and Cost Controls

### 11.1 Retry Classification

- `429`, transient `5xx`, and network failures: exponential backoff with jitter.
- Context overflow: deterministic reduction followed by bounded re-summary.
- Source unavailable: try approved alternatives or rerun the search.
- Citation does not support a claim: supplement evidence or remove the claim.
- Permission, invalid parameter, and workspace-scope failures: do not retry.

### 11.2 Circuit Breaking and Degradation

Repeated external-search failure opens a provider circuit for a bounded period.
The task may continue with authorized internal knowledge, but the report must
state that public-web coverage was unavailable.

The system never fabricates a source to satisfy the quality gate.

### 11.3 Budgets

Each task has limits for:

- model tokens and estimated cost;
- total steps;
- concurrent steps;
- fetched pages and bytes;
- replanning count;
- citation-repair rounds;
- wall-clock duration.

At the soft budget, the Supervisor narrows the remaining plan. At the hard
budget, it stops creating steps and either produces an explicitly
scope-limited report from sufficient evidence or fails without pretending the
research is complete.

## 12. Security

- Public web content is untrusted data, never executable instruction.
- System rules, user questions, tool results, and source text remain distinctly
  labeled in prompts.
- HTTP fetching restricts schemes, redirects, response size, and private or
  link-local addresses to prevent SSRF.
- Workspace and source scopes are immutable after task approval.
- Dynamic provider tools default to denied until reviewed and configured.
- Sensitive values are redacted from logs, events, and model prompts.
- Approval and denial decisions are auditable.
- No hidden chain-of-thought is stored.

## 13. Skill and Tool Extension

### 13.1 Research Skill

A `ResearchSkill` supplies on-demand domain guidance:

- applicability metadata;
- research method;
- preferred source policy;
- evidence standards;
- report schema;
- optional reviewer rules.

Only the catalog is included in the Supervisor's base prompt. Full content is
loaded after the Supervisor selects an applicable skill.

### 13.2 Research Tool Provider

A provider exposes tools through the same registry used by built-in tools.
Future MCP integration is implemented as one provider adapter, not as a second
execution path.

MCP discovery does not imply authorization. Every discovered tool still needs
an approved policy, risk classification, timeout, and workspace data boundary.

## 14. Testing Strategy

### 14.1 Unit Tests

- permission decisions;
- DAG validation and state transitions;
- lease expiry and atomic claims;
- budget calculations;
- hook ordering and failure behavior;
- evidence deduplication;
- claim-evidence validation.

### 14.2 Contract Tests

Fixed fixtures validate the structured output schemas for the Supervisor,
research specialists, Synthesizer, and Citation Reviewer.

### 14.3 Integration Tests

- PostgreSQL migrations and repositories;
- concurrent `SKIP LOCKED` claims;
- Redis and Taskiq task delivery;
- Chroma and PostgreSQL identifier consistency;
- mocked web-search and fetch providers;
- Enterprise WeChat delivery retries.

### 14.4 Recovery and Security Tests

- worker termination and lease recovery;
- duplicate callback and duplicate task delivery;
- step timeout and provider circuit breaking;
- cross-workspace access attempts;
- prompt injection in fetched pages;
- SSRF payloads;
- unapproved tool invocation;
- failed delivery without research rerun.

### 14.5 Quality Evaluation

Maintain a versioned evaluation set with research questions, expected key
claims, required source characteristics, known traps, and citation standards.
Track coverage, unsupported-claim rate, citation validity, cost, and latency.

## 15. Observability

Each research task uses a trace identifier across API, worker, tools, database
events, and delivery.

Record:

- stage and step latency;
- queue and approval wait time;
- model and tool usage;
- token and estimated monetary cost;
- source count, failure rate, and provider circuit state;
- citation validation pass rate;
- supplementary retrieval rounds;
- retry and recovery actions;
- terminal and delivery status.

The first implementation increment uses structured logs plus PostgreSQL events
and usage tables. The interfaces preserve trace and span identifiers so
OpenTelemetry can be added without redesigning the execution model.

## 16. Delivery Roadmap

### Weeks 1-2: Data and Governance

- PostgreSQL and Alembic.
- Workspace and membership model.
- SQLite migration command and cutover checks.
- Permission engine.
- Hook bus and audit events.

### Week 3: Durable Execution

- Research plans and step DAG.
- Atomic claims and leases.
- Idempotency, retry, cancellation, and budget controls.
- Task-level approval flow.

### Weeks 4-5: Multi-Agent Research

- Dynamic Supervisor.
- Knowledge and web research specialists.
- Parallel step scheduling.
- Evidence normalization and persistence.

### Week 6: Report Quality

- Synthesizer.
- Claim-evidence bindings.
- Citation Reviewer.
- Bounded supplementary retrieval and revision.

### Week 7: Reliability and Security

- Stage-specific context control.
- Provider retry, circuit breaking, and degradation.
- Prompt-injection and SSRF protections.
- Crash and lease-recovery tests.

### Week 8: Extension and Delivery

- Research Skill catalog and loader.
- Research Tool Provider interface.
- Enterprise WeChat final report delivery.
- Evaluation set, deployment documentation, and operational runbook.

## 17. Acceptance Criteria

- PostgreSQL is the authoritative production database; production no longer
  writes business data to SQLite.
- Two workspaces cannot read or mutate each other's research data.
- Multiple workers safely claim different ready steps without duplication.
- Duplicate callbacks, queue redelivery, and process restart do not duplicate
  tasks, evidence, reports, or delivery.
- Ordinary approved-policy research runs automatically.
- First-use and estimated high-cost plans require approval.
- Internal knowledge and public web retrieval can execute concurrently.
- Every material final claim has at least one validated evidence binding.
- Unsupported claims do not enter the final report as verified facts.
- External-search outage produces explicit degradation rather than fabricated
  citations.
- Soft and hard budgets, timeouts, and loop limits terminate work as designed.
- Delivery failure retries delivery only.
- The existing private research command and task-status user experience remain
  compatible.

## 18. Architecture Boundary

This design deliberately treats Learn Claude Code as a source of harness
patterns, not as an implementation template.

The Personal Butler Agent remains:

- a FastAPI and Enterprise WeChat application;
- scene-first at its messaging boundary;
- LangGraph-based for agent orchestration;
- Redis and Taskiq-based for durable asynchronous execution;
- governed by application-owned permissions and PostgreSQL state.

Coding-agent mechanisms should be introduced later only when a concrete
development-assistance use case needs them.
