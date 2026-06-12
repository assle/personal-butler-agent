# Multi-Agent Research Upgrade Design

## 1. Purpose

Upgrade Personal Butler Agent with a private-chat-only deep research capability that supports:

- factual research;
- option and product comparisons;
- complete research reports;
- automatic selection between quick synchronous answers and asynchronous research;
- parallel retrieval from authorized sources;
- budget-limited autonomous follow-up searches;
- claim-level citations and independent evidence review;
- reliable execution for a small team of tens of users across roughly 10-50 groups.

This design separates two concerns:

- Multi-agent orchestration improves research quality.
- Redis, workers, rate limits, retries, and persistent task state provide concurrency and reliability.

Higher traffic alone is not a reason to add agents.

## 2. Current Baseline

The current application is a single-process FastAPI service with scene-first routing:

- private messages enter `PrivateButlerAgent`;
- group triggers enter `GroupMentionAgent`;
- scheduled pushes use deterministic composition or `WebhookComposerAgent`;
- private chat already exposes local knowledge, web search, memory, summary, weather, translation, and reminder tools;
- graph-backed agents use LangGraph and return `AgentResponse`;
- SQLite stores current business data;
- intelligent robot callbacks use temporary `response_url` values for passive replies.

The runtime already contains multiple agent classes, but its normal execution model is controller-to-tool or controller-to-domain-agent delegation. It does not yet contain a multi-agent research workflow in which specialized roles plan, retrieve, synthesize, and independently review one task.

## 3. Scope

### 3.1 In Scope

- Deep research tasks initiated only in private chat.
- Automatic classification into quick answer, comparison research, or complete report.
- Redis-backed asynchronous execution.
- Dedicated research workers.
- Supervisor-controlled specialist agents.
- Four research rounds and an approximate five-minute default execution budget.
- Claim-level source links.
- Independent evidence review.
- Persistent task, evidence, claim, report, and delivery records.
- Enterprise WeChat custom-application messages for completion delivery.
- Administrator-maintained authorization for group knowledge bases.

### 3.2 Out of Scope

- Starting research tasks in group chat.
- Using incomplete group callback message history as research evidence.
- Automatically searching every group knowledge base a user can access.
- Inferring group membership from message history.
- Free-form agent debate or voting.
- Agents directly querying arbitrary database tables.
- Replacing existing private or group scene agents.
- A user-facing administration UI in the first delivery phase.

## 4. When Multi-Agent Is Needed

The project should enter the multi-agent phase only when several of these signals occur:

- A single research agent regularly omits material subquestions.
- Local knowledge and web research require different retrieval strategies.
- Initial evidence frequently exposes gaps that require new searches.
- The report author should not approve its own evidence.
- Intermediate evidence, claims, and revisions need separate audit records.
- A single prompt has accumulated unrelated planning, retrieval, writing, and review responsibilities.
- Data permissions cannot be enforced clearly within one broad tool set.

The following signals require infrastructure improvements rather than more agents:

- more users or groups;
- a growing queue;
- callback latency;
- failed background jobs;
- API rate limits;
- SQLite write contention.

## 5. Recommended Architecture

```text
WeCom intelligent robot private callback
    -> PrivateButlerAgent
    -> ResearchTaskClassifier
        -> quick request: existing synchronous flow
        -> deep request:
             create persistent task
             enqueue task
             immediately return task ID

Redis queue
    -> Research Worker
    -> Research Supervisor Graph
         -> Planner
         -> Knowledge Researcher
         -> Web Researcher
         -> Synthesizer
         -> Evidence Reviewer
    -> persist report and delivery job
    -> WeCom custom-application private message
```

### 5.1 Existing Scene Boundary

`PrivateButlerAgent` remains the only chat entry for research. It recognizes a research request and submits it, but it does not execute a deep research graph during callback handling.

`GroupMentionAgent` does not register research tools or routes. Group chat remains outside the research entry surface.

### 5.2 Research Task Service

`ResearchTaskService` owns:

- task creation;
- idempotency;
- initial authorization checks;
- immutable access scope creation;
- status transitions;
- cancellation requests;
- task and report lookup.

It returns a task ID immediately after a deep task has been persisted and enqueued.

### 5.3 Redis and Workers

The initial queue implementation uses Taskiq with `taskiq-redis` and
`RedisStreamBroker`. This choice matches the project's async FastAPI,
SQLAlchemy, and LangGraph execution model. The Stream broker is required
because it supports message acknowledgements; Redis Pub/Sub and list brokers
without acknowledgements are not acceptable for research or delivery jobs.

Queue usage is hidden behind a small application-owned task-dispatch interface
so a future broker migration does not alter `ResearchTaskService` or the
research graph. Taskiq result storage is not the authoritative business store;
task state and outputs remain in the application database.

Redis owns transient coordination:

- job queue;
- worker leases;
- per-user and global concurrency controls;
- retry scheduling;
- short-lived idempotency keys;
- Enterprise WeChat access-token cache.

Redis does not own the final report or authoritative task state.

Workers execute research independently of FastAPI callback processes. A worker must be able to resume a task from the latest persistent checkpoint after a crash or lease expiry.

### 5.4 Research Supervisor

The Supervisor controls the research state machine and budgets. It decides whether to:

- run retrieval;
- request another research round;
- synthesize;
- review;
- perform the single permitted revision;
- stop because evidence is sufficient or a hard limit has been reached.

The Supervisor does not perform retrieval or author the report itself.

### 5.5 Specialist Agents

#### Planner

- Classifies the requested output as factual research, comparison, or complete report.
- Decomposes the request into verifiable subquestions.
- Defines required evidence and comparison criteria.
- Produces structured research queries.

#### Knowledge Researcher

- Searches public knowledge, the user's private knowledge, personal memory, and explicitly authorized group knowledge.
- Uses only `ResearchSourceGateway`.
- Returns structured evidence records rather than prose conclusions.

#### Web Researcher

- Searches external sources.
- Records URL, title, publisher, publication time when available, retrieval time, excerpt, and query.
- May propose follow-up queries for evidence gaps.

#### Synthesizer

- Builds claims only from stored evidence.
- Distinguishes fact, inference, uncertainty, and recommendation.
- Associates every material claim with evidence IDs.
- Produces the requested answer, comparison, or complete report.

#### Evidence Reviewer

- Independently checks whether each claim is supported by its evidence.
- Checks source accessibility, conflicts, unsupported extrapolation, missing counterevidence, and citation placement.
- Returns structured findings and a quality decision.
- Cannot silently rewrite evidence or widen access scope.

## 6. Research Execution

### 6.1 Default Flow

1. The private scene classifies the request.
2. A deep request is persisted with its fixed access scope and budget.
3. The API enqueues the task and replies with the task ID.
4. The Planner decomposes the question.
5. Knowledge and web researchers run independent retrieval work in parallel where possible.
6. The Supervisor evaluates evidence coverage.
7. If critical gaps remain, it starts another targeted round.
8. Retrieval stops when evidence is sufficient, four rounds are complete, or approximately five minutes have elapsed.
9. The Synthesizer creates claims and a report with evidence bindings.
10. The Evidence Reviewer audits every material claim.
11. A failed review permits one targeted retrieval-and-revision cycle.
12. The final report and quality status are persisted.
13. A separate delivery job sends the completion message.

### 6.2 Research State

Agents exchange structured `ResearchState`, not an unbounded transcript. At minimum it contains:

- task metadata;
- immutable access scope;
- research type;
- subquestions;
- active queries;
- evidence IDs;
- identified evidence gaps;
- claims;
- review findings;
- current round;
- elapsed time and usage budgets;
- report version;
- terminal status.

Each specialist writes only fields it owns. Evidence and report bodies are persisted outside the queue payload.

### 6.3 Task States

```text
queued
  -> planning
  -> researching
  -> synthesizing
  -> reviewing
  -> revising
  -> completed

Any active state -> failed | timed_out | cancelled
```

If the time budget expires after useful evidence has been collected, the system should produce a partial report marked `evidence_limited` instead of discarding the work. `timed_out` is reserved for tasks that cannot produce a usable report.

## 7. Research Sources and Permissions

### 7.1 Default Sources

For a private research task, the allowed sources are:

- public knowledge base;
- the requesting user's private knowledge base;
- the requesting user's personal memory;
- web search;
- a group knowledge base only when the user explicitly names that group and has an active administrator-managed authorization.

Group callback message history is not a research source because the intelligent robot does not receive a complete group conversation history.

### 7.2 Group Knowledge Authorization

Group knowledge access requires both:

1. The private request explicitly identifies the target group.
2. `user_group_access` contains an enabled mapping for the requesting user and group.

The system must reject unknown, disabled, or ambiguous group access. It must not infer membership from callback history or automatically scan every authorized group.

### 7.3 Immutable Access Scope

At task creation, `ResearchTaskService` resolves and persists an immutable `access_scope` containing the permitted user, public, and optional group scopes. Workers and agents cannot add another group or user scope later.

All source access goes through `ResearchSourceGateway`, which:

- validates the task access scope;
- applies knowledge-base filters;
- calls the personal-memory service;
- calls web search;
- records task, user, source scope, query, and result references for audit.

Specialist agents never receive unrestricted database sessions or raw table access.

## 8. Persistent Data Model

### 8.1 `research_tasks`

Stores:

- task ID;
- requester ID;
- original question;
- research type;
- status;
- immutable access scope;
- current round;
- time and usage budgets;
- idempotency key;
- cancellation flag;
- timestamps;
- terminal reason or failure details.

### 8.2 `research_evidence`

Stores:

- evidence ID and task ID;
- source type and source scope;
- URL or knowledge document/chunk reference;
- title and publisher;
- publication time when available;
- retrieval time;
- excerpt;
- originating query;
- source quality metadata;
- content checksum for deduplication.

### 8.3 `research_claims`

Stores:

- claim ID and report version;
- claim text;
- claim classification such as fact, inference, or recommendation;
- linked evidence IDs;
- review status;
- reviewer findings.

### 8.4 `research_reports`

Stores:

- task ID and version;
- summary;
- body;
- citation list;
- output type;
- quality status;
- unresolved limitations;
- creation timestamp.

The database stores report content initially. Object storage can be introduced later if report volume or attachment requirements justify it.

### 8.5 `user_group_access`

Stores administrator-maintained authorization:

- user ID;
- group ID;
- optional display name;
- role;
- enabled status;
- grant and update timestamps.

### 8.6 `wecom_user_bindings`

Stores:

- intelligent-robot `open_userid`;
- custom-application plaintext `userid`;
- validation status;
- last conversion timestamp.

The binding is created or refreshed through the official `batch/openuserid_to_userid` endpoint using the custom application's access token. Conversion is allowed only for members within that application's visibility range.

## 9. Enterprise WeChat Delivery

The intelligent robot callback and custom application are separate channels:

- The intelligent robot receives the private request and uses `response_url` for the immediate task acknowledgement.
- The custom application sends the later completion notification as an application message.

`WeComAppMessageClient` owns:

- access-token acquisition and Redis caching;
- early refresh and one retry after token invalidation;
- `open_userid` to `userid` conversion;
- application message delivery;
- response-body validation.

The message client must inspect:

- `errcode`;
- `invaliduser`;
- `unlicenseduser`;
- other invalid recipient fields.

HTTP 200 alone is not success.

The completion message should contain the task ID, title, short summary, quality status, and a report entry or compact report content. Long reports should not depend on one text message because Enterprise WeChat text messages have content limits.

Delivery retries are separate from research retries. A failed notification must never rerun the research task.

## 10. Concurrency and Reliability

### 10.1 Initial Limits

- One running deep research task per user.
- Global worker concurrency of three to five.
- Parallelism only for independent retrieval operations.
- Provider-specific semaphores for LLM, web search, embeddings, and Enterprise WeChat APIs.

These are deployment defaults, not hard-coded domain rules.

### 10.2 Idempotency

Task creation uses an idempotency key derived from the inbound message identity and research submission operation. Duplicate intelligent-robot callbacks must return the existing task rather than enqueue another copy.

Each queue job and delivery job also has a stable idempotency key.

### 10.3 Retry Policy

- Retry transient network, Redis, and provider errors with exponential backoff, at most three attempts.
- Continue when one research source fails and other authorized sources remain.
- Permit one repair attempt for invalid structured LLM output.
- Persist stage checkpoints before acknowledging queue completion.
- Allow a worker to reclaim an expired job lease.
- Treat delivery retries independently from task execution.

### 10.4 Budgets

The default deep research budget is:

- at most four retrieval rounds;
- approximately five minutes;
- explicit LLM call, token, and external-search limits configured by deployment.

The Supervisor can stop early but cannot exceed hard budgets. A report generated at a limit must disclose missing evidence and unresolved questions.

## 11. Error Handling

- Authorization failure: reject task creation before enqueueing.
- Unknown group name: require an unambiguous authorized group selection.
- No useful evidence: return an evidence-insufficient report rather than fabricate an answer.
- Conflicting evidence: preserve the conflict and explain it in the report.
- Reviewer failure: retry the review stage if transient; otherwise mark quality as unreviewed and do not claim verified status.
- Review rejection: allow one targeted retrieval and revision cycle.
- Worker crash: resume from the latest persisted stage.
- Cancellation: stop scheduling new agent work, persist cancellation, and suppress completion delivery unless a cancellation notice is configured.
- User ID conversion failure: preserve the report, mark delivery failed, and expose it through task lookup.

## 12. Observability and Audit

Use `task_id` across API logs, queue jobs, graph execution, retrieval, report generation, and delivery.

Record:

- stage durations;
- queue wait time;
- current and total research rounds;
- source and evidence counts;
- LLM calls and token usage;
- external search calls;
- retry counts;
- review decisions;
- terminal and delivery failure categories.

Do not log:

- custom-application Secret;
- complete access tokens;
- complete personal-memory content;
- report bodies in ordinary application logs.

Initial operations support must allow an administrator to inspect task state, failure reason, access scope, and delivery state, and to retry delivery without rerunning research.

## 13. Testing Strategy

No test files are changed as part of this design-only work. The implementation plan must explicitly request and scope test changes because this project otherwise prohibits unrequested test modifications.

Required implementation verification includes:

- unit tests for state transitions, idempotency, budgets, token caching, user-ID conversion, and authorization;
- contract tests for every specialist agent's structured input and output;
- source-isolation tests covering public, personal, and authorized or unauthorized group knowledge;
- claim-evidence tests requiring material claims to reference evidence;
- reviewer tests that detect unsupported claims and conflicting sources;
- queue tests for duplicate jobs, retries, lease expiry, worker restart, timeout, and cancellation;
- delivery tests for expired tokens, `invaliduser`, `unlicenseduser`, business errors returned with HTTP 200, and retry idempotency;
- integration tests from private submission through report persistence and delivery, with external APIs mocked;
- manual benchmark questions covering factual research, comparison, and a complete report.

## 14. Phased Upgrade

### Phase 1: Asynchronous Foundation

- Add persistent research tasks and reports.
- Add Taskiq, `taskiq-redis`, `RedisStreamBroker`, and worker processes.
- Add task acknowledgement and lookup.
- Add custom-application token management, user-ID binding, and proactive delivery.
- Add idempotency, retry, and concurrency limits.

Exit condition: a deterministic background job can be submitted privately, completed, persisted, and delivered reliably.

### Phase 2: Deterministic Research Workflow

- Add planning, parallel authorized retrieval, synthesis, and citation validation as a fixed LangGraph workflow.
- Use one controlled research implementation rather than autonomous specialist routing.
- Establish evidence and claim schemas.

Exit condition: all three report types can be produced with traceable citations under fixed budgets.

### Phase 3: Controlled Multi-Agent Research

- Introduce the Supervisor and five specialist roles.
- Enable evidence-gap-driven follow-up research.
- Enforce four rounds and the five-minute default budget.
- Add independent evidence review and one revision cycle.

Exit condition: benchmark results demonstrate a meaningful quality improvement over Phase 2 without unacceptable cost or failure rates.

### Phase 4: Reliability and Operations

- Add persistent graph checkpoints and robust job recovery.
- Add cancellation, detailed audit records, metrics, alerts, and administrator operations.
- Tune provider rate limits and worker capacity.

### Phase 5: Scale

- Move authoritative business data from SQLite to PostgreSQL when multi-process write contention or operational requirements justify it.
- Scale worker pools independently.
- Keep queue and service interfaces stable during the database migration.

## 15. Acceptance Criteria

- Research can be initiated only from private chat.
- A deep request receives a durable task ID without waiting for research execution.
- Duplicate callbacks do not create duplicate tasks.
- The system never uses group message history as research evidence.
- Group knowledge is searched only when explicitly requested and authorized.
- Agents cannot widen the persisted access scope.
- Research stops at evidence sufficiency or the configured hard budget.
- Every material report claim has one or more traceable evidence links or is explicitly marked unsupported or uncertain.
- Evidence review is performed by a role separate from synthesis.
- A failed review causes at most one targeted revision cycle.
- Worker crashes do not lose the task or require restarting from the callback.
- Delivery failure does not rerun research.
- Enterprise WeChat delivery checks business response fields, not only HTTP status.
- Reports and audit metadata remain available even when proactive delivery fails.

## 16. Architecture Decision

Adopt a Supervisor plus specialist-agent design only after the asynchronous foundation and deterministic research workflow are working. Keep a deterministic outer state machine, immutable authorization scope, hard budgets, and persistent evidence records around all agent decisions.

This gives the project a controlled path to multi-agent research without treating agent count as a substitute for queueing, permissions, reliability, or scale engineering.

## 17. External References

- [Taskiq official documentation](https://taskiq-python.github.io/)
- [Taskiq Redis package and Redis Stream broker](https://pypi.org/project/taskiq-redis/)
- [Enterprise WeChat access token](https://developer.work.weixin.qq.com/document/path/91039)
- [Enterprise WeChat application messages](https://developer.work.weixin.qq.com/document/path/90236)
- [Enterprise WeChat intelligent-robot user ID conversion](https://developer.work.weixin.qq.com/document/path/101521)
