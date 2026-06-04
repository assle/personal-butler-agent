# Active Context

> Current project state, completed features, and deferred work. Load at session start or before planning feature work.

## Current State

The app exposes WeChat Work intelligent robot URL callback mode as the only inbound message API. Private chat messages enter `PrivateButlerAgent`; group callback messages are first persisted by `group_policy`, then allowed trigger messages enter `GroupMentionAgent`; scheduler webhook jobs use `WebhookComposerAgent` to generate markdown content before `WebhookPushClient` sends it.

Current implementation baseline:
- FastAPI app entry: `src.main:app`
- Inbound API: `GET/POST /api/wechat/aibot/callback`
- Message normalization: `src/messaging/inbound.py` converts callback dictionaries into `InboundMessage`
- Scene dispatch: `src/messaging/dispatch.py` routes private chat to `PrivateButlerAgent` and group chat through `apply_group_policy()`
- Group policy: `src/messaging/group_policy.py` saves group messages, cleans history, and allows summary/weather/simple-QA triggers
- Private chat: `PrivateButlerAgent` uses LangGraph tool calling to reach training, meal, summary, local knowledge, and web search tools
- Group mention: `GroupMentionAgent` only supports group summaries, weather placeholder replies, and lightweight Q&A; training and meal requests are rejected in group context
- Scheduler push: `SchedulerManager` reads `SCHEDULER_TARGETS_FILE`, calls `WebhookComposerAgent`, then sends markdown with `WebhookPushClient`
- Domain agents: `FitnessAgent`, `SummaryAgent`, `MealAgent`, `QAAgent`
- LLM: `langchain_openai.ChatOpenAI` pointed at DeepSeek through `LLMClient`
- Persistence: `training_records`, `user_preferences`, `group_messages`, conversation memory, knowledge-base tables, and `inbound_messages`
- Multi-turn memory: SQLite conversation memory plus LangGraph `MemorySaver` checkpointing for graph execution
- Config: `WECOM_AIBOT_BOT_ID` + `WECOM_AIBOT_TOKEN` + `WECOM_AIBOT_ENCODING_AES_KEY`; `SCHEDULER_TARGETS_FILE` enables APScheduler-driven Enterprise WeChat group webhook push

## What Is Implemented

- WeChat Work intelligent robot URL 回调模式：GET URL 验证、POST 加密回调接收、入站消息幂等落库、后台处理、通过 `response_url` 回复。
- Scene-first message flow: callback body -> `InboundMessage` -> `dispatch_message()` -> private or group scene agent.
- Private chat tool-calling controller: `PrivateButlerAgent` can call fitness, meal, summary, local knowledge, and web search tools.
- Group message passive collection: non-trigger group messages are saved and not replied to.
- Group mention restricted replies: group summary, weather placeholder, simple Q&A, and short rejection for private capabilities.
- APScheduler 企业微信群 webhook 主动推送：按本地 JSON 配置为多个群注册独立 cron，触发 `WebhookComposerAgent` 生成正文后推送 markdown 到对应群 webhook。
- Training record extraction and persistence — supports both strength and cardio training types.
- Recent-history-based training plan generation.
- Structured chat summarization — private text and group chat history.
- Preference-aware meal planning and Q&A.
- Conversation memory: 6-turn recent messages + LLM-compressed summary persisted to SQLite.
- Stage 1 knowledge-base RAG: SQLite-backed public/user/group scoped knowledge documents and chunks, local `.md`/`.txt` import CLI, scoped retrieval service, and QA/private-butler knowledge-context injection.
- Web search tool: disabled by default, configurable through `WEB_SEARCH_*`, and available to `PrivateButlerAgent` as `search_web` for current/external information.

## Deferred Work

The README and MVP spec list these as future scope:
- RAG Stage 2/3: hybrid vector retrieval, PDF/web imports, file upload UI, index rebuild operations, and broader Fitness/Meal/Summary integration.

## Working Guidance

- Treat the current app as a working scene-agent MVP with LangGraph, not a blank scaffold.
- Real message testing now goes through the WeChat Work URL callback via HTTPS tunneling or production HTTPS.
- Before feature work, read `docs/agent/patterns.md` and relevant tests.
- Before changing scope or architecture, read `docs/agent/decisions.md`.
- New cross-scene behavior should first decide which scene owns it: private chat, group mention, or scheduler composition.
- New domain agents still follow the pattern: State -> nodes -> graph -> handle(); scene agents may call them directly or expose them as tools.
