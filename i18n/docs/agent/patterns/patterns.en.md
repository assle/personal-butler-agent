# Implementation Patterns

## Application Wiring

- `src/main.py` constructs singleton service objects at module load: `LLMClient`, `IntentRouter`, each agent, and `AgentRegistry`.
- The FastAPI lifespan creates DB tables through `Base.metadata.create_all` and disposes the async engine on shutdown.
- Route modules should expose router factory functions when they need injected dependencies, following `create_debug_router(...)`.

## Request Flow

1. API route receives a Pydantic request.
2. `IntentRouter.route(message)` returns `(intent, confidence)`.
3. `AgentRegistry.get(intent)` resolves the compiled graph agent.
4. The selected agent builds initial state and runs its graph via `ainvoke()`.
5. The result is wrapped in `AgentResponse` and returned as `DebugMessageResponse`.

Keep this flow linear unless a new feature clearly needs orchestration.

## Intent Routing

- Use deterministic keyword/rule matching first for stable, common user phrases.
- Use the LLM only as a fallback for messages that rules do not classify.
- Unknown or malformed LLM classification output should fall back to `unknown`, not raise.
- Add tests for both rule hits and fallback behavior when adding intents.

## Graph Agent Boundaries

Each agent is a LangGraph `StateGraph` with three files:

```
agents/<domain>/
├── __init__.py   # Re-exports the agent class
├── state.py      # TypedDict state definition
├── nodes.py      # Single-responsibility async node functions
└── graph.py      # StateGraph assembly, agent class with handle()
```

- **State**: A `TypedDict(total=False)` defining all fields that flow through the graph. Fields are optional by default; a node only updates what it changes.
- **Nodes**: Async functions `(state: dict) -> dict` returning a partial state update. Nodes access runtime dependencies (LLM client, DB session) via `langgraph.config.get_config()`.
- **Graph**: Assembles nodes with `builder.add_node()`, sets entry point, defines edges or conditional edges, and calls `builder.compile(checkpointer=...)`.
- **Agent class**: Wraps the compiled graph. `handle(intent, message, user_id, db)` builds initial state, passes `config` with `{"configurable": {"db", "llm", "thread_id"}}`, and runs `graph.ainvoke()`.

### Adding a new agent

1. Create `src/agents/<domain>/` with `state.py`, `nodes.py`, `graph.py`, `__init__.py`.
2. Define the state TypedDict.
3. Write node functions — each does one thing, returns partial state.
4. Assemble the graph with nodes and edges.
5. Implement the agent class with `handle()`.
6. Register in `src/main.py`: instantiate and call `agent_registry.register(intent, agent)`.

### Node conventions

- Nodes that call LLM: wrap in try/except, set `error` field on failure.
- Nodes that touch DB: access session via `get_config()["configurable"]["db"]`.
- Condition functions: sync functions `(state: dict) -> str` returning the next node name.
- Keep nodes focused — if a node does two things, split it.

## Database Patterns

- Use SQLAlchemy async APIs only.
- Use `select(...)` queries with the injected `AsyncSession` from config.
- Add ORM objects to the session and `flush()` when tests or response data need generated state before route completion.
- Store extensible user preferences as JSON text under namespace keys such as `fitness` and `meal`.

## Testing Patterns

- Tests should not require real DeepSeek calls.
- Use `conftest.py`'s `mock_llm` fixture (`AsyncMock()`) for agent tests — graph nodes call `llm.chat()` / `llm.chat_json()` through config, and the mock still intercepts these.
- Use in-memory SQLite or isolated async engines in fixtures.
- Prefer focused module tests plus API smoke tests when adding behavior.
- Graph agents are tested through `handle()` — the same interface as before, so existing test patterns remain valid.
