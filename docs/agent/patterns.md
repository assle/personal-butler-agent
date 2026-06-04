# Implementation Patterns

> Established code patterns for agents, routing, database, and testing. Load before adding or modifying code.

## Application Wiring

- `src/main.py` constructs singleton service objects at module load: `LLMClient`, domain agents, `PrivateButlerAgent`, `GroupMentionAgent`, `WebhookComposerAgent`, search/knowledge/weather services, and scheduler support.
- The FastAPI lifespan creates DB tables through `Base.metadata.create_all` and disposes the async engine on shutdown.
- URL callback routes use factory functions for injected scene agents and database session factories.

## Scene-First Dispatch

Runtime message routing starts with the communication scene, not a global intent classifier.

1. URL callback messages are normalized into `InboundMessage`.
2. `dispatch_message()` routes `single` chat to `PrivateButlerAgent`.
3. `dispatch_message()` sends `group` chat through `apply_group_policy()`.
4. Scheduler webhook jobs bypass chat dispatch and call `WebhookComposerAgent`.

Keep deterministic guards outside the LLM when they protect product behavior, such as silent group collection and group capability restrictions.

## Group Policy

Group messages are saved before any reply decision. Non-trigger messages stop after persistence and cleanup. Allowed triggers enter `GroupMentionAgent`; training and meal requests are rejected in group context.

Rules:
- Empty group voice recognition returns `empty_content` and is not saved.
- Missing `chat_id` returns `missing_chat_id` and is not saved.
- Summary/weather/simple-QA triggers may reply.
- Unsupported group requests should not reach private tools.

## Private Tool-Calling Pattern

Replyable private messages enter `PrivateButlerAgent`. It owns the LangGraph `ToolNode` loop and exposes existing capabilities as tools instead of duplicating business logic.

Rules:
- Tools read `db`, `user_id`, `chat_type`, and `chat_id` from LangGraph config, not from model-supplied arguments.
- Tool functions return short text; they do not return `AgentResponse` objects.
- Existing domain agents remain the source of truth for training, meal, and summary workflows.
- Group non-trigger messages stay outside private tool calling and are collected silently.
- Do not add or modify test files unless the user explicitly asks for tests, except when an approved implementation plan explicitly requires test changes.

## Weather Tool Pattern

`src.weather` owns weather lookup. `WeatherService` extracts a location/date from the user text, calls Open-Meteo geocoding and forecast APIs, then returns a `WeatherReport`. Agent-specific tool wrappers live in the agent package that owns the tool-calling loop.

Rules:
- Private chat defines and registers `query_weather` in `src/agents/private_butler/tools.py` with the rest of the private tools.
- Group @ weather triggers bind `query_weather` from `src/agents/group_mention/tools.py` in a restricted ToolNode loop, while unsupported private capabilities remain blocked before tool execution.
- Scheduler webhook composition defines its own allowed `query_weather` wrapper in `src/agents/webhook_composer/tools.py`, then binds it in a small ToolNode loop before generating final markdown.
- Missing locations and provider failures must return a clear text fallback rather than fabricated weather.

## Graph Agent Boundaries

Each domain or scene agent is a LangGraph `StateGraph` package with this shape:

```
agents/<domain_or_scene>/
├── __init__.py
├── state.py
├── nodes.py
└── graph.py
```

- State: a `TypedDict(total=False)` defining fields that flow through the graph.
- Nodes: async functions `(state: dict) -> dict` returning partial state updates.
- Graph: assembles nodes, sets entry point, defines edges or conditional edges, and compiles the graph.
- Agent class: exposes `handle(intent, message, user_id, db, extra_state=None)` and returns `AgentResponse`.

## Database Patterns

- Use SQLAlchemy async APIs only.
- Use `select(...)` queries with the injected `AsyncSession` from config or function parameters.
- Add ORM objects to the session and `flush()` when tests or response data need generated state before route completion.
- Store extensible user preferences as JSON text under namespace keys such as `fitness` and `meal`.

## Conversation Memory Pattern

Agent `handle()` methods that need cross-turn context load memory before graph execution and save the exchange after the reply is known.

Key rules:
- Load context before `ainvoke`, save exchange after.
- Not all intents need memory; skip it for one-shot persistence or independent summary operations.
- State TypedDicts must declare `conversation_summary: str | None` and `recent_messages: list[dict]` for fields that flow through nodes.
- `ConversationMemory` handles compression transparently; callers only call `get_context` and `save_exchange`.

## Knowledge Base Pattern

Knowledge retrieval is centralized in `src/knowledge/service.py`.

- Agents must call `KnowledgeService.search()` instead of querying `knowledge_chunks` directly.
- Private chat can see `public + user`; group chat can see `public + group`.
- Group chat does not read the speaker's user-private knowledge unless a future explicit opt-in is added.
- Agents pass domain allowlists such as `["global", "qa"]`; they do not hard-code SQL filters.
- `KnowledgeService.ingest()` owns validation, checksum deduplication, chunking, and ORM writes.
- Stage 1 imports use `scripts/ingest_knowledge.py` for local `.md` / `.txt` files.

## Testing Patterns

- Tests should not require real DeepSeek calls.
- Use `conftest.py` fixtures such as `mock_llm` and isolated async DB setup.
- Prefer focused module tests plus callback/scheduler smoke tests when adding behavior.
- Graph agents are tested through `handle()`, the same interface used by scene dispatch and scheduler composition.
