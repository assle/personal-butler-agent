# Active Context

> Current project state, completed features, and deferred work. Load at session start or before planning feature work.

## Current State

The MVP is complete and migrated to LangChain + LangGraph. The app exposes `POST /api/debug/message`, routes messages through a rule-first intent router, dispatches to one of four LangGraph StateGraph agents, and persists fitness/group-message/user-preference state in SQLite. The intelligent robot uses WebSocket long-connection mode with built-in proactive push capability (APScheduler).

Current implementation baseline:
- FastAPI app entry: `src.main:app`
- Debug route: `src/router/debug.py` — supports chat_type/chat_id for group chat simulation
- WeChat Work intelligent robot WebSocket long-connection: `src/wechat/ws_client.py` — 消息接收、非阻塞后台处理、回复、主动推送 `aibot_send_msg`
- Intent routing: `src/intent/rules.py` and `src/intent/router.py`
- Agents: `FitnessAgent`, `SummaryAgent` (text + group), `MealAgent`, `QAAgent`
- Agent registry: `src/agents/registry.py` — 7 intent→agent mappings
- LLM: `langchain_openai.ChatOpenAI` pointed at DeepSeek
- Persistence: `training_records`, `user_preferences`, `group_messages`
- Multi-turn memory: LangGraph `MemorySaver` checkpointing (in-memory, per user_id thread)
- Verification baseline: 132 tests passing with `DEEPSEEK_API_KEY=test uv run pytest -q`
- Config: `WECOM_AIBOT_BOT_ID` + `WECOM_AIBOT_SECRET` for intelligent robot WebSocket long-connection mode; `SCHEDULER_*` 系列字段支持 `|` 分隔多目标+独立消息+混合指定/自动 intent，通过 IntentRouter 自动路由; `WECOM_CORP_SECRET` for server API access_token / user info queries (paired with `WECHAT_CORP_ID`)

## What Is Implemented

- Debug API request/response schema (with chat_type/chat_id for group simulation).
- WeChat Work intelligent robot WebSocket 长连接模式 (消息接收、非阻塞后台处理、回复、主动推送 `aibot_send_msg`).
- APScheduler 定时 LLM 推送 (可配置 cron、多目标(`|` 分隔 TYPE/ID/MESSAGE/INTENT 按位置配对)、每个目标独立消息和 intent（空位由 IntentRouter 自动规则/LLM 判定），通过长连接模式主动推送).
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
- Voice message support: WeChat Work built-in voice recognition text extracted from JSON `voice.content` (intelligent robot), routed through existing intent pipeline. Empty recognition silently ignored.
- Agent personality: each agent (QA/小管家, Fitness/铁块教练, Meal/小厨, Summary/会议纪要员) has a distinct persona with defined character, speaking style, and emotional tone.
- Conversation memory: 6-turn recent messages + LLM-compressed summary persisted to SQLite; QA, Fitness(today_plan), and Meal agents maintain cross-turn context.
- Stage 1 knowledge-base RAG: SQLite-backed public/user/group scoped knowledge documents and chunks, local `.md`/`.txt` import CLI, scoped retrieval service, and QAAgent knowledge-context injection.
- WeChat Work user identity mapping: `WeComTokenManager` (access_token caching with asyncio.Lock, 5-minute early refresh), `WeComUserService` (user info query + SQLite caching with 24h TTL, graceful degradation to stale cache on API failure), `WeComUser` ORM model. Inject `user_name` / `user_department` into agent extra_state for personalized replies. Requires `WECOM_CORP_SECRET` + `WECHAT_CORP_ID` both configured; silently skipped when not set.

## Deferred Work

The README and MVP spec list these as future scope:
- RAG Stage 2/3: hybrid vector retrieval, PDF/web imports, file upload UI, index rebuild operations, and broader Fitness/Meal/Summary integration.

## Working Guidance

- Treat the current app as a working MVP with LangGraph, not a blank scaffold.
- Preserve the debug endpoint while adding real integrations unless the user asks to replace it.
- Before feature work, read `docs/agent/patterns.md` and relevant tests.
- Before changing scope or architecture, read `docs/agent/decisions.md`.
- New agents follow the pattern: State → nodes → graph → register in `registry.py`.
