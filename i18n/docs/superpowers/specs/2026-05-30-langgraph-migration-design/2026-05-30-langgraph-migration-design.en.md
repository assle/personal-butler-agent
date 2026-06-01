# LangGraph Migration Design

## Purpose

Refactor the current MVP to adopt LangChain + LangGraph as the agent framework while preserving the existing FastAPI surface, SQLite persistence, and debug endpoint contract. The primary motivators are: (1) align the project's tech stack with current agent-development interview expectations, and (2) establish a cleaner extension pattern for future modules (multi-turn memory, RAG, scheduled tasks, research assistant, etc.) without overcomplicating the current working code.

## Architecture Overview

### Stack

- **HTTP layer**: FastAPI (unchanged)
- **LLM access**: `langchain_openai.ChatOpenAI` pointed at DeepSeek (replaces `openai.AsyncOpenAI`)
- **Agent orchestration**: LangGraph `StateGraph` per domain agent
- **Persistence**: SQLAlchemy 2 async + SQLite (unchanged)
- **Scheduling**: APScheduler (already in deps, wired later)

### Project Structure (target)

```
src/
├── main.py              # FastAPI lifespan, dependency wiring (minor edits)
├── config.py             # pydantic-settings (add langchain-specific keys)
├── router/
│   └── debug.py          # HTTP route, intent dispatch via registry (thinned)
├── intent/
│   ├── router.py         # IntentRouter: rule-first + ChatModel fallback
│   └── rules.py          # keyword matching (unchanged)
├── agents/
│   ├── registry.py       # intent → graph agent central registry
│   ├── base.py           # BaseGraphAgent ABC: compile + run
│   ├── fitness/
│   │   ├── state.py      # FitnessState TypedDict
│   │   ├── nodes.py      # node functions (single-responsibility)
│   │   └── graph.py      # StateGraph assembly + compile
│   ├── summary/          # same pattern
│   ├── meal/
│   └── qa/
├── graph/
│   ├── common.py         # shared state fields, common nodes (error_handler)
│   └── memory.py         # MemorySaver / SqliteSaver checkpoint config
├── llm/
│   └── client.py         # ChatOpenAI wrapper (DeepSeek-compatible)
├── models/               # SQLAlchemy ORM (unchanged)
├── schemas/              # Pydantic request/response (unchanged)
└── db/                   # engine, session, base (unchanged)
```

### What stays unchanged

- `POST /api/debug/message` request/response schema
- SQLAlchemy ORM models and `AsyncSession` injection pattern
- Keyword-based rule matching for intent classification
- `AgentResponse` / `DebugMessageResponse` Pydantic types
- Test strategy: mock LLM clients, isolated DB engines

## LangGraph Agent Pattern

Each domain agent becomes a `StateGraph` with typed state and single-purpose nodes. The agent's `handle()` method builds initial state and runs the graph — the caller sees no difference.

### State definition (example: FitnessAgent)

```python
class FitnessState(TypedDict):
    intent: str
    message: str
    user_id: str
    raw_result: Optional[str]
    parsed_items: list[dict]
    saved_records: list[dict]
    history_text: str
    preferences: dict
    reply: str
    data: Optional[dict]
    error: Optional[str]
```

### Node mapping (FitnessAgent)

| Path           | Nodes                                                              |
|----------------|--------------------------------------------------------------------|
| `log_training` | extract → validate → persist → format                             |
| `today_plan`   | fetch_history → fetch_preferences → generate_plan → format_response |

### Graph topology

```
    __start__
        │
    [classify]  ← condition edge by intent
     /      \
log_training  today_plan
  │ extract      │ fetch_history
  │ validate     │ fetch_preferences
  │ persist      │ generate_plan
  │ format       │ format
     \      /
    __end__
```

### Error handling

Each LLM-calling node catches exceptions and sets `error` field. A condition edge checks for error and routes to a common `error_handler` node that formats a degraded response. LLM unavailability never crashes the request.

## Data Flow

```
POST /api/debug/message
  │
  ▼
IntentRouter.route(message)
  ├── rules.py match → (intent, 1.0)
  └── no match → ChatModel classify → (intent, confidence)
  │
  ▼
registry.get(intent) → compiled GraphAgent
  │
  ▼
agent.handle(intent, message, user_id, db)
  ├── initial_state = {intent, message, user_id, ...}
  ├── graph.ainvoke(state, config={"configurable": {"thread_id": user_id}})
  └── extract reply + data → AgentResponse
  │
  ▼
DebugMessageResponse
```

## Memory Support

LangGraph's checkpointer provides multi-turn conversation memory with near-zero custom code.

- **MVP phase**: `MemorySaver` (in-memory, no persistence between restarts).
- **Post-MVP**: switch to `SqliteSaver` backed by SQLite, same `thread_id = user_id` key.
- Agents that need history reference prior state fields populated by earlier turns.
- Isolated per domain: a fitness conversation doesn't leak into a meal-planning conversation.

## Extension Points

| Feature               | How it plugs in                                                            |
|-----------------------|----------------------------------------------------------------------------|
| New agent (e.g. research) | `agents/research/` → state + nodes + graph → register in `registry.py` |
| Multi-turn memory     | Swap `MemorySaver` → `SqliteSaver`, no agent code changes                  |
| RAG                   | Add `retrieve` node using LangChain document loaders + vectorstore         |
| Scheduled tasks       | APScheduler job calls `agent.handle()` directly, same graph path           |
| Message summarization | Current `SummaryAgent` rewritten as graph, same interface                  |

## Migration Strategy

1. **Phase 1 — Infrastructure**: Add `langchain`, `langgraph`, `langchain-openai` deps. Replace `src/llm/client.py` with `ChatOpenAI` wrapper. Keep exact same `chat()` and `chat_json()` method signatures so existing agents still work.

2. **Phase 2 — First agent**: Convert `FitnessAgent` to StateGraph. This validates the pattern. All fitness tests must pass first.

3. **Phase 3 — Remaining agents**: Convert SummaryAgent, MealAgent, QAAgent one at a time. Each conversion is self-contained — one agent doesn't block another.

4. **Phase 4 — Cleanup**: Remove the old `BaseAgent` ABC, add `BaseGraphAgent`. Add `registry.py`, thin out the intent→agent mapping in `debug.py`.

5. **Phase 5 — Memory & extensions**: Wire `MemorySaver`, then add new agents or modules as needed.

Each phase should leave `DEEPSEEK_API_KEY=test uv run pytest -q` green.

## Testing

- **Node unit tests**: Pass mock LLM through graph node, assert state change.
- **Graph integration tests**: Compile graph with mock ChatModel, `graph.ainvoke()`, assert final reply.
- **API smoke tests**: `POST /api/debug/message` with mock client, assert response shape (same as current).
- **No real DeepSeek calls in CI**: mock at the `ChatOpenAI` level.
