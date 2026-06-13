# Active Context

> Current project state, completed features, and deferred work. Load at session start or before planning feature work.

## Current State

The app exposes WeChat Work intelligent robot URL callback mode as the only inbound message API. Private chat messages enter `PrivateButlerAgent`; group callback messages are first persisted by `group_policy`, then allowed trigger messages enter `GroupMentionAgent`; scheduler webhook jobs either send raw configured content with optional weather appended or use `WebhookComposerAgent` to generate markdown before `WebhookPushClient` sends it.

Current implementation baseline:
- FastAPI app entry: `src.main:app`
- Inbound API: `GET/POST /api/wechat/aibot/callback`
- Message normalization: `src/messaging/inbound.py` converts callback dictionaries into `InboundMessage`
- Scene dispatch: `src/messaging/dispatch.py` routes private chat to `PrivateButlerAgent` and group chat through `apply_group_policy()`
- Group policy: `src/messaging/group_policy.py` saves group messages, cleans history, classifies allowed triggers, and passes the category to `GroupMentionAgent`
- Private chat: `PrivateButlerAgent` uses LangGraph tool calling (ReAct pattern) with 15 tools: summary, RAG search, web search, weather, reminders, translation, memory CRUD, chat-based knowledge ingestion (add_to_knowledge)
- Group mention: `GroupMentionAgent` supports weather, polls, translation, and chat-based knowledge ingestion (add_to_knowledge, auto-scoped to group)
- Scheduler push: `SchedulerManager` reads `SCHEDULER_TARGETS_FILE`, sends `mode="raw"` content directly with optional `weather_query` appended, or calls `WebhookComposerAgent` for `mode="compose"` targets, then sends markdown with `WebhookPushClient`
- Runtime agents: `PrivateButlerAgent`, `GroupMentionAgent`, `WebhookComposerAgent`, `SummaryAgent`, `ReminderAgent`, `PollAgent`
- LLM: `langchain_openai.ChatOpenAI` pointed at DeepSeek through `LLMClient`
- Persistence: PostgreSQL as production database (`DATABASE_URL` + `DATABASE_REQUIRE_MIGRATIONS=true` with Alembic) or SQLite for dev (`DATABASE_URL=sqlite+aiosqlite:///butler.db DATABASE_REQUIRE_MIGRATIONS=false`) + ChromaDB (`chroma_data/` for knowledge chunks vector index)
- Multi-turn memory: SQLite conversation memory plus LangGraph `MemorySaver` checkpointing for graph execution
- Config: `WECOM_AIBOT_BOT_ID` + `WECOM_AIBOT_TOKEN` + `WECOM_AIBOT_ENCODING_AES_KEY`; `SCHEDULER_TARGETS_FILE` enables APScheduler-driven Enterprise WeChat group webhook push

## What Is Implemented

- WeChat Work intelligent robot URL 回调模式：GET URL 验证、POST 加密回调接收、入站消息幂等落库、后台处理、通过 `response_url` 回复。
- Scene-first message flow: callback body -> `InboundMessage` -> `dispatch_message()` -> private or group scene agent.
- Private chat tool-calling controller: `PrivateButlerAgent` can call summary, local knowledge, web search, weather, and reminder tools.
- Group message passive collection: non-trigger group messages are saved and not replied to.
- Group mention restricted replies: group summary, real weather lookup, simple Q&A, polls, translation, and short rejection for unavailable capabilities. Dispatch-provided categories prevent duplicate classification.
- APScheduler 企业微信群 webhook 主动推送：按本地 JSON 配置为多个群注册独立 cron；`mode="raw"` 原样发送固定正文并可通过 `weather_query` 追加当天真实天气，`mode="compose"` 继续触发 `WebhookComposerAgent` 生成正文，再推送 markdown 到对应群 webhook。
- 私聊提醒：`ReminderAgent` 解析自然语言创建提醒，支持显式提醒词（"提醒我开会"）和隐含表达（"制定会议"、"10分钟后"、"半小时后"）；`SchedulerManager` 每分钟扫描到期并通过群 webhook 以 `<@userid> 事项` 推送；私聊确认展示 target `display_name` 与本地时区。`WebhookPushClient` 检查响应 body 的 `errcode`，避免 WeChat 返回 HTTP 200 但业务失败静默丢失。
- Structured chat summarization — private text and group chat history.
- Knowledge-based private Q&A and lightweight group Q&A.
- Conversation memory: 6-turn recent messages + LLM-compressed summary persisted to SQLite.
- Stage 3 Chroma-backed RAG: ChromaDB 向量存储（嵌入式，零运维）替代 SQLite JSON 向量；Query Rewriting + 多路粗筛（关键词/FTS/向量） + LLM Re-rank 精排；段落感知分块 + overlap；支持 `.md`/`.txt`/`.pdf`/网页 四种格式导入。`KnowledgeService` 兼容旧接口，不传 ChromaStore 则回退到旧检索逻辑。
- Web search tool: disabled by default, configurable through `WEB_SEARCH_*`, and available to `PrivateButlerAgent` as `search_web` for current/external information.
- Weather lookup: Open-Meteo-backed weather data is available in private chat through `PrivateButlerAgent` tools, in group @ through a restricted `GroupMentionAgent` ToolNode loop, and in scheduler webhook raw composition through `weather_query`; no API key is required.
- Group poll voting: `PollAgent` handles full lifecycle — create polls with natural-language end time, cast/change votes via @bot, view live results, and end polls manually. `SchedulerManager` registers one-shot APScheduler jobs for auto-ending; results are pushed to the group via webhook. `GroupWebhook` table maps `chat_id` to webhook URL, enabling dynamic push without static config.
- LLM translation: `translate_text` function shared by `PrivateButlerAgent` (as a LangChain tool) and `GroupMentionAgent` (as a keyword-triggered node). Supports any language pair via LLM prompting, with target-language parsing from natural-language requests like "翻译成英文：你好世界".
- Deep personalized memory (Stage 1): 双层存储——`memory_fragments` 碎片池 + `user_profile` 确认画像。`MemoryService` 支持碎片管理、聚合升级（occurrences ≥ 3）、重要性计算（来源×0.4 + 置信度×0.4 + 信号强度×0.2）、衰减和矛盾检测。`extractor.py` 隐式从每条私聊消息中提取画像碎片（preference/fact/habit/relationship），旁路异步执行不阻塞回复。prompt 注入升级为分类结构化画像 + 行为指导。`EmbeddingService` 新增 `batch_embed()` 批量 API 支持，碎片创建时缓存向量。
- Semantic embedding: `EmbeddingService` uses DashScope Qwen3-Embedding API (`text-embedding-v4`, 1024-dim) for semantic vector matching. Falls back to local character n-gram hashing when API key is not configured or the API call fails, ensuring zero-downtime degradation.
- Observability: Full-chain trace logging (`[trace:inject]` / `[trace:sidepath]` for memory extraction pipeline, `[trace:search]` for RAG retrieval). Logs include elapsed timings per stage, candidate counts, and source attribution.
- Async research foundation (Phase 1): Private chat submits "深度研究：<问题>" → durable SQLite task with callback msgid idempotency → Redis Stream (Taskiq) enqueue → independent worker generates unreviewed_foundation LLM draft → separate delivery task converts open_userid via WeCom custom-app API and pushes result to user. Feature gate: `RESEARCH_ENABLED` defaults to false. Worker command: `taskiq worker src.research.broker:broker src.research.tasks`.
- Enterprise WeChat custom-application messaging: `WeComAppMessageClient` with `RedisAccessTokenCache`, open_userid-to-userid conversion, errcode validation, and token refresh (40014/42001).
- PostgreSQL as production database with Alembic schema management: `DATABASE_URL` defaults to `postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler`; `DATABASE_REQUIRE_MIGRATIONS=true` verifies Alembic revision at head on startup; `alembic upgrade head` required before first start. SQLite supported for dev via `DATABASE_URL=sqlite+aiosqlite:///butler.db DATABASE_REQUIRE_MIGRATIONS=false`.
- Workspace and WorkspaceMember models for multi-tenant governance: each workspace scopes users, research tasks, and knowledge scopes independently.
- WorkspaceService for membership resolution: `resolve_member()` identifies the caller's workspace identity before business logic execution.
- PermissionEngine with 5-rule priority chain: structured governance for workspace-aware operations, rules evaluated in priority order.
- HookBus for research lifecycle events: emits lifecycle hooks (critical hooks block on failure), owned by `src/governance/`.
- Workspace-scoped research tasks: `workspace_id` assigned at creation and never changes; cross-workspace access prevented by service-layer queries.
- Dialect-aware knowledge keyword search: SQLite FTS5 for local dev, PostgreSQL `tsvector`/`tsquery` for production — selected automatically via `db.dialect.name`.
- SQLite-to-PostgreSQL one-time migration CLI: `butler-migrate-to-pg` exports SQLite data and imports to PostgreSQL for migration from dev environment.
- Phase 2 研究执行 DAG：计划 → 步骤 → 审批 → 执行 → 重试，Taskiq Worker 认领步骤
- 12 状态研究任务生命周期（submitted → planning → awaiting_approval → running → ...）
- DAG 步骤依赖与租约恢复（PG SKIP LOCKED 并发认领，过期租约回收）
- 确定性审批策略（首次使用 + 高成本审批），私聊批准/拒绝命令
- 预算追踪（token 计数、成本微单位、软硬限制）
- 计划校验器（DAG 无环检测、工具白名单、预算限制）
- 审计事件日志（自动脱敏密钥和令牌）
- 私聊命令 `批准研究任务 R20260613-XXXXXXXX` 批准待审批计划
- 私聊命令 `拒绝研究任务 R20260613-XXXXXXXX：预算过高` 拒绝待审批计划
- Phase 3 结构化 LLM Supervisor：Supervisor 产生经过校验的 PlanDraft JSON；检索与规划解耦，每步写入规范化证据
- Phase 3 知识库 + 网页检索 Specialist：KnowledgeResearcher 和 WebResearcher 产生归一化 ToolExecutionResult
- Phase 3 管辖工具注册表：ResearchToolRegistry 集成权限检查和 Hook 总线
- Phase 3 工作空间隔离证据去重：ResearchEvidenceService 按 SHA-256 去重，同工作空间相同 hash 复用
- Phase 3 步骤执行器：ResearchStepExecutor 执行已派发工具调用，持久化证据，更新步骤 DAG 状态

## Deferred Work

- Reminder Stage 2: 日报/周报提醒内容生成，优先复用 Summary/WebhookComposer 等当前运行 agent 生成周期报告。
- 图片 OCR 识别。
- Docker 化部署、CI/CD、E2E 测试。

## Working Guidance

- Treat the current app as a production-stage scene-agent application with LangGraph, not a blank scaffold.
- Real message testing now goes through the WeChat Work URL callback via HTTPS tunneling or production HTTPS.
- Before feature work, read `docs/agent/patterns.md` and relevant tests.
- Before changing scope or architecture, read `docs/agent/decisions.md`.
- New cross-scene behavior should first decide which scene owns it: private chat, group mention, or scheduler composition.
- New domain agents still follow the pattern: State -> nodes -> graph -> handle(); scene agents may call them directly or expose them as tools.
