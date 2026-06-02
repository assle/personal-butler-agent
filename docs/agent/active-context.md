# Active Context

> Current project state, completed features, and deferred work. Load at session start or before planning feature work.

## Current State

The MVP is complete and migrated to LangChain + LangGraph. The app exposes `POST /api/debug/message` and `POST /api/wechat/callback` (self-built app), routes messages through a rule-first intent router, dispatches to one of four LangGraph StateGraph agents, and persists fitness/group-message/user-preference state in SQLite. The intelligent robot HTTP callback has been replaced by WebSocket long-connection mode with built-in proactive push capability (APScheduler).

Current implementation baseline:
- FastAPI app entry: `src.main:app`
- Debug route: `src/router/debug.py` — supports chat_type/chat_id for group chat simulation
- WeChat Work self-built app callback: `src/wechat/router.py` — GET URL verification + POST message receive with AES-256-CBC encryption, CorpID validation, passive encrypted XML reply
- WeChat Work intelligent robot WebSocket long-connection: `src/wechat/ws_client.py` — 消息接收、非阻塞后台处理、回复、主动推送 `aibot_send_msg`（替代 HTTP 回调模式）
- Intent routing: `src/intent/rules.py` and `src/intent/router.py`
- Agents: `FitnessAgent`, `SummaryAgent` (text + group), `MealAgent`, `QAAgent`
- Agent registry: `src/agents/registry.py` — 7 intent→agent mappings
- LLM: `langchain_openai.ChatOpenAI` pointed at DeepSeek
- Persistence: `training_records`, `user_preferences`, `group_messages`
- Multi-turn memory: LangGraph `MemorySaver` checkpointing (in-memory, per user_id thread)
- Verification baseline: 118 tests passing with `DEEPSEEK_API_KEY=test uv run pytest -q`
- Config: `WECOM_AIBOT_BOT_ID` + `WECOM_AIBOT_SECRET` for intelligent robot WebSocket long-connection mode (replaces HTTP callback + `response_url` reply); `SCHEDULER_CRON`/`SCHEDULER_MESSAGE`/etc. for APScheduler timed push (alongside existing `WECHAT_CORP_ID` + `WECHAT_TOKEN` + `WECHAT_ENCODING_AES_KEY` for self-built app)

## What Is Implemented

- Debug API request/response schema (with chat_type/chat_id for group simulation).
- WeChat Work self-built app callback (AES-256-CBC crypto, XML parsing, passive encrypted XML reply).
- WeChat Work intelligent robot WebSocket 长连接模式 (消息接收、非阻塞后台处理、回复、主动推送 `aibot_send_msg`).
- APScheduler 定时 LLM 推送 (可配置 cron/目标/触发消息，通过长连接模式主动推送).
- Rule-first classification for known intent keywords.
- DeepSeek/OpenAI-compatible LLM fallback classification via LangChain ChatOpenAI.
- Training record extraction and persistence — supports both strength (sets/reps/weight) and cardio (duration/speed/incline/calories) training types (FitnessAgent StateGraph).
- Recent-history-based training plan generation (FitnessAgent StateGraph).
- Structured chat summarization — private chat text and group chat history (SummaryAgent StateGraph with conditional routing).
- Group chat message passive collection: all group messages saved to DB, trigger keywords ("总结"/"摘要"/"概括"/"汇总") initiate summarization.
- Preference-aware meal planning and Q&A (MealAgent, QAAgent StateGraphs).
- Agent registry for centralized intent-to-agent dispatch.
- Multi-turn conversation memory via LangGraph MemorySaver (in-memory, per user_id thread).
- Test fixtures that mock LLM behaviors and use isolated test DB setup.
- Voice message support: WeChat Work built-in voice recognition text extracted from XML `<Recognition>` (self-built app) and JSON `voice.content` (intelligent robot), routed through existing intent pipeline. Empty recognition silently ignored.
- Agent personality: each agent (QA/小管家, Fitness/铁块教练, Meal/小厨, Summary/会议纪要员) has a distinct persona with defined character, speaking style, and emotional tone.
- Conversation memory: 6-turn recent messages + LLM-compressed summary persisted to SQLite; QA, Fitness(today_plan), and Meal agents maintain cross-turn context.
- Stage 1 knowledge-base RAG: SQLite-backed public/user/group scoped knowledge documents and chunks, local `.md`/`.txt` import CLI, scoped retrieval service, and QAAgent knowledge-context injection.

## Deferred Work

The README and MVP spec list these as future scope:
- RAG Stage 2/3: hybrid vector retrieval, PDF/web imports, file upload UI, index rebuild operations, and broader Fitness/Meal/Summary integration.
- Async customer-service message reply for self-built app callback (self-built app still uses synchronous passive XML reply with 5-second timeout limitation; intelligent robot long-connection mode already supports asynchronous reply).

## Working Guidance

- Treat the current app as a working MVP with LangGraph, not a blank scaffold.
- Preserve the debug endpoint while adding real integrations unless the user asks to replace it.
- Before feature work, read `docs/agent/patterns.md` and relevant tests.
- Before changing scope or architecture, read `docs/agent/decisions.md`.
- New agents follow the pattern: State → nodes → graph → register in `registry.py`.
