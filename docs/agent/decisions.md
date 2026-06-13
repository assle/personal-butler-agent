# Architecture Decisions

> Recorded architecture decisions and rationale. Load before making design choices or scope changes.

## ADR-001: FastAPI Producer + Optional Taskiq Workers

The default deployment is a single-process FastAPI app backed by SQLite + ChromaDB (embedded). When async research is enabled (`RESEARCH_ENABLED=true`), the architecture becomes multi-process: the FastAPI producer enqueues tasks via Redis Stream, and one or more Taskiq worker processes execute research and delivery jobs independently.

Reasoning:
- The default single-process mode keeps debugging and deployment simple for everyday chatbot use.
- APScheduler handles timed jobs in-process; ChromaDB runs embedded (same process, local file).
- Redis is only required when research is enabled. The feature gate defaults to false, preserving zero-dependency startup for the base case.
- Taskiq workers decouple long-running LLM calls from HTTP request handling, preventing callback timeouts.
- Worker processes open their own SQLite sessions, avoiding cross-process session conflicts.

## ADR-002: SQLite + ChromaDB Dual Storage

## ADR-002: SQLite + ChromaDB Dual Storage

SQLite (via async SQLAlchemy) stores structured data: documents, chunks, reminders, polls, user profiles, memory fragments, conversation messages. ChromaDB (embedded) stores knowledge chunk embeddings for vector search.

Reasoning:
- SQLite is sufficient for structured data at personal scale; SQLAlchemy keeps the model layer portable to PostgreSQL.
- ChromaDB provides native ANN search with metadata filtering, replacing the previous JSON-vector-in-SQLite approach.
- Both are zero-config, single-file (or single-directory) storage compatible with ADR-001.

## ADR-004: Agent-per-Domain Boundaries

Status: Retired from the current runtime on 2026-06-11.

The original architecture placed fitness, summary, meal, and Q&A behavior in separate LangGraph packages.

Reasoning:
- Each agent can own domain prompts, DB access, validation, and response shaping.
- StateGraph nodes isolate responsibilities further: extraction, validation, persistence, and formatting are separate functions.
- Tests stay focused by domain.
- Future modules can follow the same interface (state + nodes + graph + handle method) without rewriting scene dispatch.

Retirement note:
- Fitness, meal, and standalone QA packages were removed after the product direction narrowed.
- The current runtime uses scene agents plus focused Summary and Reminder agents.

## ADR-006: DeepSeek Through LangChain ChatOpenAI

The LLM wrapper uses `langchain_openai.ChatOpenAI` with configurable DeepSeek-compatible base URL and model.

Reasoning:
- It keeps provider details centralized in `src/llm/client.py`.
- Tests can mock the wrapper without touching business agents.
- Future provider changes should happen behind the wrapper.
- LangChain's ChatOpenAI provides a standard interface that integrates with LangGraph's ecosystem.

## ADR-007: LangGraph StateGraph for Agent Orchestration

Graph-backed agents use LangGraph `StateGraph` rather than linear class method chains.

Reasoning:
- StateGraph provides a first-class state machine that natively supports multi-step workflows, conditional routing, error recovery, and checkpointing.
- Node-per-responsibility decomposition makes agents easier to test, extend, and reason about.
- LangGraph's `MemorySaver` checkpointing gives multi-turn conversation memory with near-zero custom code.
- LangGraph is the current industry standard for agent development and aligns with interview expectations.
- Simple agents such as Summary and Reminder stay linear; scene agents use conditional routing or tool loops where needed.
- The `handle()` interface remains identical — callers (routes, tests, schedulers) are unaffected.

## ADR-008: 智能机器人 URL 回调作为可靠入站通道

项目使用智能机器人 URL 回调模式作为唯一消息入站通道。

Reasoning:
- **避免长连接离线窗口丢入站消息**: URL 回调由企微主动投递到公网 HTTPS 服务，入站可靠性更符合“消息不丢”的目标。
- **先落库再处理**: 回调路由按 `msgid` 写入 `inbound_messages`，重复回调幂等去重，HTTP 立即返回成功，后台再运行 LLM/agent。
- **回复不阻塞回调**: agent 处理完成后通过消息体里的 `response_url` 发送 markdown 回复，避免 LLM 调用占用 HTTP 回调响应时间。
- **可观测和可补偿**: `pending/processing/processed/failed` 状态让失败消息可查询，后续可增加启动扫描和人工重放。

Trade-off:
- URL 回调重新需要公网域名、HTTPS、Token 和 EncodingAESKey。
- 智能机器人原通道只适合被动回复；主动群推送通过企业微信群机器人 webhook 独立完成。
- 当前只保证“入站已接收可追踪”，不承诺在 response_url 过期或长时间宕机后仍能原通道回复。

## ADR-009: Sliding Window + LLM-Compressed Conversation Memory

Conversation memory uses a 6-turn (12-message) sliding window in prompt context, with older messages compressed into a single summary string by LLM and persisted to SQLite.

Reasoning:
- **Sliding window (recent messages in prompt)**: Keeps the most recent exchanges in full fidelity so agents can reference specific user statements and assistant replies. 6 turns is small enough to fit in context, large enough to cover a coherent topic thread.
- **LLM-compressed summary**: Older messages beyond the window are not discarded — they are periodically compressed into a one-sentence summary by a lightweight LLM call. This preserves key facts and preferences from earlier exchanges without consuming token budget.
- **SQLite persistence**: Summaries and messages survive process restarts, unlike LangGraph's in-memory `MemorySaver` which is only for single-session graph checkpointing.
- **Automatic compression trigger**: When a user exceeds 24 total messages, the oldest 12 are compressed. This keeps the message table bounded without manual cleanup.
- **Intent-conditional memory**: Not all agents/contexts benefit from context. Summary agents are independent per call. QA and private butler flows load conversation memory where useful.

Trade-off: The compression prompt is a separate LLM call, adding latency and cost per ~12 exchanges. For the current single-user MVP scale this is negligible. At higher throughput, compression could be deferred to a background job.

## ADR-010: Single TrainingRecord Table for Strength and Cardio

Status: Retired from the current runtime on 2026-06-11.

The `training_records` table was extended with nullable cardio columns (`duration_minutes`, `speed`, `incline`, `calories`) rather than creating a separate `cardio_records` table or using table inheritance.

Reasoning:
- **Unified history query**: A user's training history (`fetch_training_history`) spans both types. A single table with a `training_type` discriminator keeps the query simple — one `SELECT` with `WHERE user_id = ? ORDER BY date DESC`.
- **Shared fields**: `date`, `exercise`, `user_id`, and `created_at` are common to both types. Nullable type-specific columns avoid duplicating these.
- **MVP pragmatism**: At the current single-user scale, a separate table would add complexity (UNION queries, dual persistence paths) without meaningful benefit.
- **LLM extraction coherence**: The `EXTRACTION_PROMPT` returns a unified JSON array where each item declares its `training_type`. Persisting to one table matches this mental model.

Trade-off: Many columns will be NULL depending on training type. For a small-scale MVP this is acceptable. At higher throughput with analytics needs, a separate `cardio_records` table or a normalized schema may be more appropriate.

Retirement note:
- The training ORM mapping and agent code were removed.
- Existing SQLite files may retain the historical table until a future Alembic migration decides whether to export or drop it.

## ADR-012: 移除自建应用服务端 API 依赖

智能机器人 URL 回调模式只保留 `WECOM_AIBOT_BOT_ID`、`WECOM_AIBOT_TOKEN` 和 `WECOM_AIBOT_ENCODING_AES_KEY`。项目不再暴露 `WECOM_CORP_ID` / `WECOM_CORP_SECRET`，也不再初始化基于自建应用 Secret 的用户信息查询服务。

Reasoning:
- **配置来源一致**: 智能机器人后台没有自建应用 Secret，保留该字段会误导部署。
- **集成边界更清晰**: 当前目标是可靠接收消息并通过 `response_url` 被动回复，不混入自建应用服务端 API。
- **降低启动依赖**: 应用启动不再需要额外 access_token 链路，减少配置失败面。

Trade-off: agent 上下文只使用回调消息中的 `userid`、`chatid` 等基础字段，不再查询用户姓名、部门、头像。若未来确实需要用户详情，应作为单独的自建应用/OAuth 集成重新设计。

## ADR-013: 调度器目标配置改为 JSON 文件

旧的 `.env` 扁平多字段调度配置已被 `SCHEDULER_TARGETS_FILE` JSON 目标文件取代。

Reasoning:
- 每个企业微信群需要独立 cron、webhook 和触发消息，JSON 对象比多个位置配对字符串更清晰。
- webhook 地址是敏感凭据，真实 local JSON 文件可以单独加入 `.gitignore`。
- 配置文件可以保留 `enabled` 开关，便于临时关闭单个群。

Trade-off: JSON 文件比单行 `.env` 多一个本地文件，但明显降低了多群配置错位风险。

## ADR-015: 企业微信群 Webhook 作为主动推送通道

URL 回调模式继续负责智能机器人入站消息和 `response_url` 被动回复；主动推送改由企业微信群机器人 webhook 独立完成。APScheduler 通过 `SCHEDULER_TARGETS_FILE` 读取本地 JSON 目标配置，为每个群注册独立 cron job。`mode="raw"` target 到点后原样发送 `message`，并可用 `weather_query` 直接查询天气后追加到同一条消息；`mode="compose"` target 到点后调用 `WebhookComposerAgent` 生成内容，再发送 markdown 到对应 webhook。

Reasoning:
- URL 回调模式负责入站和被动回复；主动群通知需要独立出站通道。
- 企业微信“消息推送”类 webhook 适合群通知，不适合伪装成私聊主动推送，因此当前主动通道只面向群。
- JSON 文件比 `.env` 中多个 `|` 分隔字段更适合保存多群、多 cron、多 webhook 的配置，且真实 webhook 文件可加入 `.gitignore` 避免提交密钥。

Trade-off:
- 群 webhook 是单向推送通道，不能接收用户回复。
- webhook 地址本身是敏感凭据，需要按密钥管理。
- 每个群独立 job 会增加调度配置数量，但目标边界更清晰。

## ADR-016: Scene Agents Replace Global Intent And All-Purpose Controller

Private chat, group mention, and scheduled webhook push have different product boundaries. A single all-purpose controller and global intent router made these boundaries implicit and fragile.

Decision:
- Private chat uses `PrivateButlerAgent`.
- Group mention uses `GroupMentionAgent`.
- Scheduler webhook push uses deterministic raw composition for fixed content and weather, and uses `WebhookComposerAgent` only for `mode="compose"` targets.
- Local debug/dev message API, legacy long-connection compatibility, global intent routing package, and the old all-purpose controller package are removed.

Reasoning:
- Scene boundaries are easier to test and document.
- Group chat cannot accidentally access training or meal tools.
- Webhook composition is no longer treated like a user chat request.
- Real integration testing now uses WeChat Work URL callback through HTTPS tunneling.

## ADR-017: Group Classification And Scheduler Module Ownership

Group trigger classification is owned by `apply_group_policy()`. The selected category is passed through scene dispatch into `GroupMentionAgent`; the agent only classifies when called directly without a preclassified category.

Scheduler responsibilities are split by ownership:
- `models.py`: target data.
- `config.py`: JSON loading and validation.
- `client.py`: outbound webhook HTTP.
- `manager.py`: APScheduler lifecycle and jobs.
- `__init__.py`: stable public exports only.

Reasoning:
- One classification result prevents policy and agent keyword rules from drifting during the normal callback flow.
- Focused scheduler modules are easier to test and change independently.
- Re-exporting the existing public API avoids unnecessary call-site migration.

## ADR-018: GroupWebhook DB Table for Dynamic Push Targets

Static `SCHEDULER_TARGETS_FILE` is designed for fixed cron-driven recurring pushes. Dynamic one-shot tasks (such as poll auto-end) need to resolve a `chat_id` to a webhook URL at runtime, without requiring every group to appear in the static JSON config.

Decision:
- Add a `group_webhooks` table mapping `chat_id` → `webhook_url` (+ optional `display_name`).
- `PollAgent` and `SchedulerManager._push_poll_result` query this table to find the webhook URL for the target group.
- The static `SCHEDULER_TARGETS_FILE` is preserved for its existing use case (recurring scheduled pushes). Both mechanisms coexist.

Reasoning:
- Creating a poll should not require editing a JSON config file.
- A DB table is the natural storage for runtime-discovered group metadata.
- The static config remains the right choice for fixed recurring content; the DB table serves dynamic one-shot push needs.

Trade-off: Two webhook-resolution paths exist (file-based and DB-based). Merging them into a single table is deferred until the static config use case justifies the migration cost.

## ADR-019: Shared Utility over Standalone Agent for Simple LLM Operations

Translation is a single LLM call ("translate X to Y"). Creating a full agent (state + nodes + graph + handle) for this would be excessive ceremony.

Decision:
- Place `translate_text()` in a shared `src/agents/translate.py` module, not a standalone `TranslationAgent`.
- Both `PrivateButlerAgent` (via LangChain tool) and `GroupMentionAgent` (via graph node) call the same function.
- No new state, graph, or ORM model is required.

Reasoning:
- A single async function is the right abstraction for a single LLM call.
- The "shared utility" pattern is simpler than the "agent per domain" pattern and should be the default for capabilities that are pure LLM transformations with no state, persistence, or multi-step workflow.

When to use each pattern:
- **Shared utility** (`translate_text`): single LLM call, no state, no persistence, no multi-step flow.
- **Domain agent** (`PollAgent`, `SummaryAgent`): multi-step workflow, DB persistence, conditional routing, or state management.

## ADR-020: API-First Embedding with Local Fallback

`EmbeddingService` now supports two modes: DashScope Qwen3-Embedding API (semantic, 1024-dim) and local character n-gram hashing (lexical, 256-dim).

Decision:
- When `DASHSCOPE_API_KEY` is configured, `embed()` calls the DashScope API first.
- If the API call fails (network error, auth failure, rate limit), `embed()` silently falls back to local hashing.
- `similarity()` is mode-agnostic — it computes cosine similarity regardless of how the vectors were produced.
- Callers (`MemoryService`, `KnowledgeService`) are unaware of which mode is active; they only see the `embed()` and `similarity()` interface.

Reasoning:
- Qwen3-Embedding provides true semantic matching (e.g., "不喝咖啡" ≈ "不喜欢咖啡"), enabling the personalized memory feature.
- Local hashing costs nothing, requires no API key, and works offline — appropriate as the zero-config default.
- Silent fallback means the app never crashes because the embedding API is down; it degrades gracefully to a lower-quality but functional mode.
- The fallback is invisible to callers, keeping the EmbeddingService abstraction clean.

Trade-off: Silent fallback means the operator won't be alerted when the API is down unless they proactively check. For a personal bot this is acceptable; for production, logging or metrics would be added.

## ADR-021: ReAct Single-Agent Architecture

Private chat and group chat agents use the ReAct (Reasoning + Acting) pattern via LangGraph StateGraph: `agent(call_model) → tools_condition → ToolNode → agent → extract_reply`. Domain agents (Summary, Reminder, Poll) are invoked synchronously as tools, not as independent ReAct agents.

Reasoning:
- Single-agent ReAct covers 95% of personal assistant use cases: LLM reasons about the user's intent, selects the right tool, observes the result, and decides whether to continue or reply.
- Domain agents (SummaryAgent, ReminderAgent, PollAgent) have focused, linear workflows — wrapping them as tools is simpler than giving each its own ReAct loop.
- LangGraph's compiled StateGraph with checkpointing provides multi-turn memory without custom state management.
- ReAct is the current industry standard for agent development and aligns with interview expectations.

Trade-off: Domain agents cannot independently reason or chain multiple tools. If a future use case requires multi-step domain reasoning (e.g., "check reminders, then create a summary based on them"), a multi-agent Supervisor pattern would be the natural upgrade path.

## ADR-022: Chat-Based Knowledge Ingestion

Users can add content to the knowledge base directly from chat via `add_to_knowledge` tool. Private chat auto-scopes to `user` (private), group chat auto-scopes to `group`. The tool internally calls `KnowledgeService.ingest()` with a synthetic source (`chat://{chat_type}/{user_id}`).

Reasoning:
- CLI-based import (`butler-ingest-knowledge`) is powerful but requires terminal access. Chat-based ingestion removes this friction.
- Auto-scoping eliminates the need for users to understand scope concepts (public/user/group).
- This pattern is used by ChatGPT Memory, Slack bots, Coze, and other production AI assistants.

## ADR-023: Webhook Delivery Verification

`WebhookPushClient.send_markdown()` checks the WeChat API response body `errcode` field in addition to HTTP status. The WeChat webhook API returns HTTP 200 even on business errors (e.g., invalid key), so HTTP status alone is insufficient.

Reasoning:
- Silent delivery failures waste user trust — reminders appear "sent" but never arrive.
- The fix is minimal (one JSON parse + errcode check) with zero breaking changes.

## ADR-024: Redis Stream + Taskiq for Async Research

When research is enabled, Redis Stream (via Taskiq) serves as the message queue between the FastAPI producer and independent worker processes. Database state is authoritative; the queue carries only task IDs.

Reasoning:
- **Decoupling**: Long-running LLM research calls must not block HTTP callback responses. Workers run in separate processes.
- **Delivery isolation**: Research execution and report delivery are independent Taskiq tasks. If delivery fails, the completed report is preserved; if research fails, delivery is never enqueued.
- **Feature gate**: `RESEARCH_ENABLED` defaults to false. Without Redis, the application runs as a single process with zero queue dependencies.
- **Taskiq over Celery**: Taskiq is async-native (no sync workers), simpler configuration, and integrates cleanly with existing async SQLAlchemy sessions.
- **Authoritative DB**: Task state lives in SQLite, not in the queue. Workers reopen sessions and re-derive state. This prevents split-brain between queue state and DB state.

Trade-off: SQLite concurrent writers (API + 3 workers) may show `database is locked` under high load. PostgreSQL migration (Phase 5) addresses this.

## ADR-025: Independent WeChat Custom-Application Delivery Channel

Research results are delivered via WeChat Work custom-application API (`WECOM_APP_*`), completely separate from the intelligent robot URL callback (`WECOM_AIBOT_*`).

Reasoning:
- The intelligent robot can only reply within 30 minutes via `response_url` — insufficient for async research that may take minutes.
- Custom-application messages can be sent to any user at any time, enabling true async push.
- The old `WECOM_CORP_ID`/`WECOM_CORP_SECRET` fields (retired in ADR-012) were removed because the intelligent robot callback does not need them. The new `WECOM_APP_*` fields are deliberately named differently to avoid confusion.
- `open_userid` (from robot callback) and `userid` (for app messages) are different ID spaces. `WeComUserBinding` table caches the conversion.

## ADR-026: PostgreSQL as Authoritative Team Database

Status: Accepted. Replaces SQLite for production. Reasoning: multi-user concurrency, proper schema migrations via Alembic, tsvector FTS support. SQLite remains supported for single-user development.

## ADR-027: Alembic Owning Production Schema

Status: Accepted. Alembic manages all DDL; `Base.metadata.create_all` is dev-only fallback. Startup verifies revision at head when `database_require_migrations=True`.

## ADR-028: Immutable Workspace Scope

Status: Accepted. Research tasks are created with a `workspace_id` that never changes. Cross-workspace access is prevented by service-layer queries, not just database constraints.

## ADR-029: Application-Owned Permission and Hook Interfaces

Status: Accepted. `PermissionEngine` and `HookBus` provide structured governance without external policy engines. Simple priority-ordered rules cover the current single-team use case.

## ADR-030: Durable Research DAG with Leases

Status: Accepted. Steps are first-class DB rows with leases, not in-memory ephemeral state. Workers claim via row locks. Expired leases auto-recover. Plans are versioned and side-effect free until approved.

## ADR-031: Structured Supervisor over Ad-Hoc Planning

Status: Accepted. Phase 3 introduces an LLM-based ResearchSupervisor that produces a validated PlanDraft JSON, replacing the deterministic fixture planner from Phase 2.

Reasoning:
- **Structured output guarantees schema compliance**: The supervisor uses `ainvoke_structured()` with Pydantic schema, producing PlanDraft with typed steps, dependencies, and budgets. The planner from Phase 2 was hardcoded fixture data with no LLM reasoning.
- **Retrieval is isolated from planning**: The supervisor never searches the web or knowledge base during planning. Each retrieval step is explicitly declared in PlanDraft with tool_name and input_payload, to be executed by ResearchStepExecutor.
- **Each step writes normalized evidence**: Tool execution produces ToolExecutionResult with an `evidence` array. ResearchEvidenceService deduplicates by SHA-256(workspace_id + source_ref + excerpt). Evidence is workspace-scoped.
- **Governed tool registry**: ResearchToolRegistry enforces permission policies (read/internal_write/external_action) and emits HookBus events before and after each tool call, ensuring auditability.
- **Worker-process ownership**: The supervisor, registry, step executor, and specialist providers are instantiated in Taskiq worker processes (src/research/tasks.py), not the FastAPI main process. This keeps the producer thin and worker self-contained.

Trade-off: The supervisor always evaluates `first_use=True` when calling ApprovalPolicy, because it lacks access to the WorkspaceContext (resolved in the main process). This means every plan requires first-use approval by default, even if the user was already approved in the past. The approval flow in the callback router resolves this by checking the actual WorkspaceMember.research_approved_once.

## ADR-032: Evidence-Grounded Citation Quality Gate

Status: Accepted.

Synthesis and citation validation are separate LLM calls with independent context. The Synthesizer receives evidence; the Reviewer receives claims and their bound evidence only. A deterministic local gate can override an LLM "pass" when material claims lack evidence bindings or have unresolved error findings. Repair is bounded (max rounds + budget); failure escalation is explicit.

## ADR-033: Bounded Retry and Circuit Breaking

Status: Accepted. Typed failure categories determine retry policy. Provider circuit breaker opens after configurable consecutive failures. Deterministic tool-gate prevents prompt injection from bypassing the registry.

