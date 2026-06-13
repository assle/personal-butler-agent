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
- Enterprise WeChat custom-application messaging: `WeComAppMessageClient` with `RedisAccessTokenCache`, open_userid-to-userid conversion, errcode validation, and token refresh (40014/42001).

- Phase 4 citation quality: 证据引用综合 (ReportSynthesisService) → 独立引用审查 (CitationReviewService) → 确定性质量门 → 有限修复协调 (QualityRepairCoordinator)。结构化结论 (ResearchClaim) + 证据绑定 (ResearchClaimEvidence) + 审查发现 (ResearchReviewFinding)。仅已验证报告可投递。
- Phase 5: 失败分类与指数退避重试、Redis 熔断器、阶段上下文构建器、SSRF 防护 URL 策略、安全网页抓取、prompt 注入边界、步骤看门狗
- Phase 6: 定义研究技能 (ResearchSkillManifest) + general-research 技能目录；Skill 目录扫描与按名加载 (ResearchSkillCatalog, ResearchSkillLoader)；内置研究工具注册 (BuiltinResearchDependencies) + MCP Provider 预留边界；研究技能提交消息更新；split_text_utf8 长文本按 UTF-8 边界拆分投递；离线质量评估框架 (EvaluationRunner + CLI)；全链路追踪上下文 (TraceContext)；CI workflow (.github/workflows/test.yml)；运维手册 (docs/operations/research-runbook.md)
- Phase 3: Structured Supervisor 规划 + Knowledge/Web Specialist 检索 + 受控工具注册表 + 证据持久化
- Phase 2: DAG 步骤 + 审批 + 预算
- Phase 1: PostgreSQL + workspace 治理 + Alembic
