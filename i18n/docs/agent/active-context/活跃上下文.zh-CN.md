# Active Context

## Current State

The MVP is complete and migrated to LangChain + LangGraph. The app exposes `POST /api/debug/message` and `POST /api/wechat/callback`, routes messages through a rule-first intent router, dispatches to one of four LangGraph StateGraph agents, and persists fitness/group-message/user-preference state in SQLite.

Current implementation baseline:
- FastAPI app entry: `src.main:app`
- Debug route: `src/router/debug.py` — supports chat_type/chat_id for group chat simulation
- WeChat Work callback: `src/wechat/router.py` — GET URL verification + POST message receive with encryption
- Intent routing: `src/intent/rules.py` and `src/intent/router.py`
- Agents: `FitnessAgent`, `SummaryAgent` (text + group), `MealAgent`, `QAAgent`
- Agent registry: `src/agents/registry.py` — 7 intent→agent mappings
- LLM: `langchain_openai.ChatOpenAI` pointed at DeepSeek
- Persistence: `training_records`, `user_preferences`, `group_messages`
- Multi-turn memory: LangGraph `MemorySaver` checkpointing (in-memory, per user_id thread)
- Verification baseline: 68 tests passing with `DEEPSEEK_API_KEY=test uv run pytest -q`

## What Is Implemented

- Debug API request/response schema (with chat_type/chat_id for group simulation).
- WeChat Work self-built app callback (AES-256-CBC crypto, XML parsing, passive reply).
- Rule-first classification for known intent keywords.
- DeepSeek/OpenAI-compatible LLM fallback classification via LangChain ChatOpenAI.
- Training record extraction and persistence (FitnessAgent StateGraph).
- Recent-history-based training plan generation (FitnessAgent StateGraph).
- Structured chat summarization — private chat text and group chat history (SummaryAgent StateGraph with conditional routing).
- Group chat message passive collection: all group messages saved to DB, trigger keywords ("总结"/"摘要"/"概括"/"汇总") initiate summarization.
- Preference-aware meal planning and Q&A (MealAgent, QAAgent StateGraphs).
- Agent registry for centralized intent-to-agent dispatch.
- Multi-turn conversation memory via LangGraph MemorySaver (in-memory, upgradeable to SqliteSaver).
- Test fixtures that mock LLM behaviors and use isolated test DB setup.

## Deferred Work

The README and MVP spec list these as future scope:
- Group robot webhook pushes for announcements, digests, and notifications (WechatWebhookClient exists, needs scheduler + agent integration).
- APScheduler jobs for scheduled reminders and daily reports.
- Persistent conversation memory (SqliteSaver — MemorySaver is the current in-memory placeholder).
- RAG or knowledge-base integration.
- Async customer-service message reply (currently only passive reply is implemented).

## Working Guidance

- Treat the current app as a working MVP with LangGraph, not a blank scaffold.
- Preserve the debug endpoint while adding real integrations unless the user asks to replace it.
- Before feature work, read `docs/agent/patterns.md` and relevant tests.
- Before changing scope or architecture, read `docs/agent/decisions.md`.
- New agents follow the pattern: State → nodes → graph → register in `registry.py`.
