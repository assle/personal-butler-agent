# Active Context

## Current State

The MVP is complete and migrated to LangChain + LangGraph. The app exposes `POST /api/debug/message` as a stand-in for the future WeChat Work callback, routes messages through a rule-first intent router, dispatches to one of four LangGraph StateGraph agents, and persists fitness/user-preference state in SQLite.

Current implementation baseline:
- FastAPI app entry: `src.main:app`
- Debug route: `src/router/debug.py`
- Intent routing: `src/intent/rules.py` and `src/intent/router.py`
- Agents: `FitnessAgent`, `SummaryAgent`, `MealAgent`, `QAAgent` — each a LangGraph `StateGraph` with typed state and single-purpose nodes
- Agent registry: `src/agents/registry.py` — central intent-to-agent mapping
- LLM: `langchain_openai.ChatOpenAI` pointed at DeepSeek
- Persistence: `training_records` and `user_preferences`
- Multi-turn memory: LangGraph `MemorySaver` checkpointing (in-memory, per user_id thread)
- Verification baseline: 29 tests passing with `DEEPSEEK_API_KEY=test uv run pytest -q`

## What Is Implemented

- Debug API request/response schema.
- Rule-first classification for known intent keywords.
- DeepSeek/OpenAI-compatible LLM fallback classification via LangChain ChatOpenAI.
- Training record extraction and persistence (FitnessAgent StateGraph: extract → validate → persist → format).
- Recent-history-based training plan generation (FitnessAgent StateGraph: fetch_history → fetch_prefs → generate → format).
- Structured chat summarization (SummaryAgent StateGraph).
- Preference-aware meal planning and Q&A (MealAgent, QAAgent StateGraphs).
- Agent registry for centralized intent-to-agent dispatch.
- Multi-turn conversation memory via LangGraph MemorySaver (in-memory, upgradeable to SqliteSaver).
- Test fixtures that mock LLM behaviors and use isolated test DB setup.

## Deferred Work

The README and MVP spec list these as future scope:
- Real WeChat Work self-built application callback integration.
- Group robot webhook pushes for announcements, digests, and notifications.
- APScheduler jobs for scheduled reminders and daily reports.
- Persistent conversation memory (SqliteSaver — MemorySaver is the current in-memory placeholder).
- RAG or knowledge-base integration.
- Multi-user group chat message collection.

## Working Guidance

- Treat the current app as a working MVP with LangGraph, not a blank scaffold.
- Preserve the debug endpoint while adding real integrations unless the user asks to replace it.
- Before feature work, read `docs/agent/patterns.md` and relevant tests.
- Before changing scope or architecture, read `docs/agent/decisions.md`.
- New agents follow the pattern: State → nodes → graph → register in `registry.py`.
