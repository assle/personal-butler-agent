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
- Private chat: `PrivateButlerAgent` uses LangGraph tool calling to reach summary, local knowledge, web search, weather, and reminder tools
- Group mention: `GroupMentionAgent` only supports group summaries, weather lookups, and lightweight Q&A; training and meal requests are rejected in group context
- Scheduler push: `SchedulerManager` reads `SCHEDULER_TARGETS_FILE`, sends `mode="raw"` content directly with optional `weather_query` appended, or calls `WebhookComposerAgent` for `mode="compose"` targets, then sends markdown with `WebhookPushClient`
- Runtime agents: `PrivateButlerAgent`, `GroupMentionAgent`, `WebhookComposerAgent`, `SummaryAgent`, `ReminderAgent`
- LLM: `langchain_openai.ChatOpenAI` pointed at DeepSeek through `LLMClient`
- Persistence: `group_messages`, conversation memory, knowledge-base tables, reminders, reminder runs, and `inbound_messages`
- Multi-turn memory: SQLite conversation memory plus LangGraph `MemorySaver` checkpointing for graph execution
- Config: `WECOM_AIBOT_BOT_ID` + `WECOM_AIBOT_TOKEN` + `WECOM_AIBOT_ENCODING_AES_KEY`; `SCHEDULER_TARGETS_FILE` enables APScheduler-driven Enterprise WeChat group webhook push

## What Is Implemented

- WeChat Work intelligent robot URL 回调模式：GET URL 验证、POST 加密回调接收、入站消息幂等落库、后台处理、通过 `response_url` 回复。
- Scene-first message flow: callback body -> `InboundMessage` -> `dispatch_message()` -> private or group scene agent.
- Private chat tool-calling controller: `PrivateButlerAgent` can call summary, local knowledge, web search, weather, and reminder tools.
- Group message passive collection: non-trigger group messages are saved and not replied to.
- Group mention restricted replies: group summary, real weather lookup, simple Q&A, and short rejection for unavailable capabilities. Dispatch-provided categories prevent duplicate classification.
- APScheduler 企业微信群 webhook 主动推送：按本地 JSON 配置为多个群注册独立 cron；`mode="raw"` 原样发送固定正文并可通过 `weather_query` 追加当天真实天气，`mode="compose"` 继续触发 `WebhookComposerAgent` 生成正文，再推送 markdown 到对应群 webhook。
- 私聊创建群 webhook 提醒：`ReminderAgent` 将自然语言提醒解析为 SQLite 提醒任务；`SchedulerManager` 每分钟扫描到期提醒，并通过对应群 webhook 以 `<@userid> 事项` 形式提醒；私聊确认和提醒列表使用 target `display_name` 与本地时区展示。
- Structured chat summarization — private text and group chat history.
- Knowledge-based private Q&A and lightweight group Q&A.
- Conversation memory: 6-turn recent messages + LLM-compressed summary persisted to SQLite.
- Stage 2 QA-first knowledge-base RAG: SQLite-backed public/user/group scoped knowledge documents and chunks, local `.md`/`.txt` import CLI, scoped retrieval service, private-butler knowledge-tool injection, and hybrid lexical + SQLite FTS + local embedding retrieval.
- Web search tool: disabled by default, configurable through `WEB_SEARCH_*`, and available to `PrivateButlerAgent` as `search_web` for current/external information.
- Weather lookup: Open-Meteo-backed weather data is available in private chat through `PrivateButlerAgent` tools, in group @ through a restricted `GroupMentionAgent` ToolNode loop, and in scheduler webhook raw composition through `weather_query`; no API key is required.

## Deferred Work

The README and MVP spec list these as future scope:
- RAG Stage 3: PDF/web imports, file upload UI, persisted index rebuild operations, optional external vector store, and broader summary/webhook composition integration if needed.
- Reminder Stage 2: 日报/周报提醒内容生成，优先复用 Summary/WebhookComposer 等当前运行 agent 生成周期报告。

## Working Guidance

- Treat the current app as a working scene-agent MVP with LangGraph, not a blank scaffold.
- Real message testing now goes through the WeChat Work URL callback via HTTPS tunneling or production HTTPS.
- Before feature work, read `docs/agent/patterns.md` and relevant tests.
- Before changing scope or architecture, read `docs/agent/decisions.md`.
- New cross-scene behavior should first decide which scene owns it: private chat, group mention, or scheduler composition.
- New domain agents still follow the pattern: State -> nodes -> graph -> handle(); scene agents may call them directly or expose them as tools.
