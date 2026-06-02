# Architecture Decisions

> Recorded architecture decisions and rationale. Load before making design choices or scope changes.

## ADR-001: Single-Process FastAPI MVP

The MVP is a single-process FastAPI application. It avoids Redis, Celery, Kafka, Docker, and Kubernetes until the product needs them.

Reasoning:
- The current goal is a local, understandable personal-butler demo.
- A single process keeps debugging and deployment simple.
- Future scheduling can start with APScheduler before introducing external workers.

## ADR-002: SQLite as the Memory Layer

The MVP stores training records and user preferences in SQLite through async SQLAlchemy.

Reasoning:
- SQLite is enough for local single-user or small private use.
- SQLAlchemy keeps the model layer portable if the app later moves to PostgreSQL.
- JSON preferences allow new domains to add namespaces without immediate migrations.

## ADR-003: Rule-First Intent Routing

Intent routing checks deterministic rules before calling the LLM fallback.

Reasoning:
- Common commands should be cheap, stable, and testable.
- LLM fallback handles natural-language variation without making every route probabilistic.
- Invalid LLM output must degrade to `unknown` safely.

## ADR-004: Agent-per-Domain Boundaries

Fitness, summary, meal, and Q&A behavior live in separate agent packages, each implemented as a LangGraph `StateGraph`.

Reasoning:
- Each agent can own domain prompts, DB access, validation, and response shaping.
- StateGraph nodes isolate responsibilities further: extraction, validation, persistence, and formatting are separate functions.
- Tests stay focused by domain.
- Future modules can follow the same interface (state + nodes + graph + registry) without rewriting the dispatcher.

## ADR-005: Debug Endpoint Before WeChat Work Integration

The MVP keeps `POST /api/debug/message` as the first integration surface.

Reasoning:
- It makes local and automated tests independent of WeChat Work callback signing and network setup.
- Real WeChat Work callback support should be added beside this route first, not by deleting the debug route.

## ADR-006: DeepSeek Through LangChain ChatOpenAI

The LLM wrapper uses `langchain_openai.ChatOpenAI` with configurable DeepSeek-compatible base URL and model.

Reasoning:
- It keeps provider details centralized in `src/llm/client.py`.
- Tests can mock the wrapper without touching business agents.
- Future provider changes should happen behind the wrapper.
- LangChain's ChatOpenAI provides a standard interface that integrates with LangGraph's ecosystem.

## ADR-007: LangGraph StateGraph for Agent Orchestration

Each agent is implemented as a LangGraph `StateGraph` rather than a linear class method chain.

Reasoning:
- StateGraph provides a first-class state machine that natively supports multi-step workflows, conditional routing, error recovery, and checkpointing.
- Node-per-responsibility decomposition makes agents easier to test, extend, and reason about.
- LangGraph's `MemorySaver` checkpointing gives multi-turn conversation memory with near-zero custom code.
- LangGraph is the current industry standard for agent development and aligns with interview expectations.
- Simple agents (QA, Summary) stay simple with a linear graph. Complex agents (Fitness) gain conditional routing between sub-intents.
- The `handle()` interface remains identical — callers (routes, tests, schedulers) are unaffected.

## ADR-008: Separate Intelligent Robot Callback from Self-Built App Callback

The intelligent robot API callback (`/api/wechat/robot/callback`) is implemented as a separate router and route from the self-built app callback (`/api/wechat/callback`).

Reasoning:
- **Different message format**: The intelligent robot sends JSON with nested fields (`from.userid`, `text.content`, `chatid`, `response_url`), while the self-built app sends XML/flat JSON (`FromUserName`, `Content`, `ChatId`). Attempting to share a parser would create fragile branching logic.
- **Different reply mechanism**: The robot uses active reply via `response_url` POST (JSON), while the self-built app uses passive encrypted XML reply. These are fundamentally different code paths.
- **Different crypto receiveid**: The robot uses `""` (empty string), the self-built app uses CorpID. Sharing the decrypt call with different receiveid values is bug-prone.
- **Independent config**: Separate `WECHAT_ROBOT_TOKEN`/`WECHAT_ROBOT_ENCODING_AES_KEY` from `WECHAT_CORP_ID`/`WECHAT_TOKEN`/`WECHAT_ENCODING_AES_KEY`. Each can be enabled independently.
- **Independent failure domains**: A bug in the robot callback won't break the self-built app callback, and vice versa.
- **response_url msgtype constraint**: The robot's `response_url` only supports `markdown` and `template_card` msgtypes — not `text`. This constraint only applies to the robot router.

## ADR-009: Sliding Window + LLM-Compressed Conversation Memory

Conversation memory uses a 6-turn (12-message) sliding window in prompt context, with older messages compressed into a single summary string by LLM and persisted to SQLite.

Reasoning:
- **Sliding window (recent messages in prompt)**: Keeps the most recent exchanges in full fidelity so agents can reference specific user statements and assistant replies. 6 turns is small enough to fit in context, large enough to cover a coherent topic thread.
- **LLM-compressed summary**: Older messages beyond the window are not discarded — they are periodically compressed into a one-sentence summary by a lightweight LLM call. This preserves key facts and preferences from earlier exchanges without consuming token budget.
- **SQLite persistence**: Summaries and messages survive process restarts, unlike LangGraph's in-memory `MemorySaver` which is only for single-session graph checkpointing.
- **Automatic compression trigger**: When a user exceeds 24 total messages, the oldest 12 are compressed. This keeps the message table bounded without manual cleanup.
- **Intent-conditional memory**: Not all agents/contexts benefit from context. `log_training` (one-shot record) and Summary agents (independent per call) skip memory loading. QA, Fitness `today_plan`, and Meal always load it.

Trade-off: The compression prompt is a separate LLM call, adding latency and cost per ~12 exchanges. For the current single-user MVP scale this is negligible. At higher throughput, compression could be deferred to a background job.

Trade-off: The two routers (`src/wechat/router.py` and `src/wechat/robot_router.py`) share some structural similarity (GET URL verification, POST decrypt + signature check). The shared crypto and message-building utilities in `src/wechat/crypto.py` and `src/wechat/messages.py` prevent code duplication at the lower layers while keeping the routing logic separate where it diverges.

## ADR-010: Single TrainingRecord Table for Strength and Cardio

The `training_records` table was extended with nullable cardio columns (`duration_minutes`, `speed`, `incline`, `calories`) rather than creating a separate `cardio_records` table or using table inheritance.

Reasoning:
- **Unified history query**: A user's training history (`fetch_training_history`) spans both types. A single table with a `training_type` discriminator keeps the query simple — one `SELECT` with `WHERE user_id = ? ORDER BY date DESC`.
- **Shared fields**: `date`, `exercise`, `user_id`, and `created_at` are common to both types. Nullable type-specific columns avoid duplicating these.
- **MVP pragmatism**: At the current single-user scale, a separate table would add complexity (UNION queries, dual persistence paths) without meaningful benefit.
- **LLM extraction coherence**: The `EXTRACTION_PROMPT` returns a unified JSON array where each item declares its `training_type`. Persisting to one table matches this mental model.

Trade-off: Many columns will be NULL depending on training type. For a small-scale MVP this is acceptable. At higher throughput with analytics needs, a separate `cardio_records` table or a normalized schema may be more appropriate.

## ADR-011: 智能机器人长连接模式替代回调模式

智能机器人从 HTTP 回调模式切换到 WebSocket 长连接模式。

Reasoning:
- **主动推送**: 长连接模式支持 `aibot_send_msg` 主动推送，回调模式仅能通过 `response_url` 被动回复。APScheduler 定时推送依赖此能力。
- **简化部署**: 长连接模式无需公网 IP/域名/SSL、无需消息加解密，降低部署门槛。
- **消除 5 秒超时**: WebSocket 长连接无 HTTP 响应超时限制，LLM 处理时长不受限制。
- **统一通道**: 消息接收、回复、主动推送全部走一条 WebSocket，消除群机器人 webhook 的冗余依赖。
- **官方演进方向**: 2026 年 3 月企业微信发布长连接模式，这是官方重点迭代方向。

Trade-off: 需要维护 WebSocket 连接（心跳、断线重连），增加了一定的运维复杂度。但这被更简单的部署和统一的消息通道所抵消。

## ADR-012: 企微用户身份映射 — SQLite 缓存 + 服务端 API

通过 `corp_id` + `corp_secret` 调用企微 `/cgi-bin/user/get` 获取用户详细信息（姓名/部门/头像等），缓存到本地 SQLite（TTL 24h），在消息处理流程中注入 agent extra_state。

Reasoning:
- **不依赖网页 OAuth**: Bot 消息回调中已有 `userid`，无需用户主动授权即可查询基本信息。网页 OAuth 路径需要用户手动触发且仅适用于 Web 入口。
- **SQLite 缓存而非实时查询**: 用户信息变化频率低，24h TTL 大幅减少 API 调用次数（每次消息都实时查询会触发企微 API 频率限制）。过期数据在 API 失败时作为降级回退。
- **独立 service 模块**: `WeComTokenManager` + `WeComUserService` 遵循项目的 service 层模式，WS 和 HTTP 两条消息路径复用同一套逻辑，避免代码重复。
- **access_token 内存缓存**: token 7200s TTL，提前 5 分钟刷新，`asyncio.Lock` 防并发刷新风暴，避免每次用户查询都调 `gettoken`。
- **可选配置**: `WECOM_CORP_SECRET` 未配置时整套功能静默跳过，不影响现有消息流程。

Trade-off: 用户信息不够实时（最长 24h 延迟），但姓名/部门/头像等信息变化频次远低于消息交互频次。如果需要实时数据，可将 TTL 调短或提供手动刷新接口。
