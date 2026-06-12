# Implementation Patterns

> Established code patterns for agents, routing, database, and testing. Load before adding or modifying code.

## Application Wiring

- `src/main.py` constructs only runtime singleton objects: `LLMClient`, `SummaryAgent`, `ReminderAgent`, `PollAgent`, scene agents, search/knowledge/weather services, and scheduler support.
- The FastAPI lifespan creates DB tables through `Base.metadata.create_all` and disposes the async engine on shutdown.
- URL callback routes use factory functions for injected scene agents and database session factories.

## Scene-First Dispatch

Runtime message routing starts with the communication scene, not a global intent classifier.

1. URL callback messages are normalized into `InboundMessage`.
2. `dispatch_message()` routes `single` chat to `PrivateButlerAgent`.
3. `dispatch_message()` sends `group` chat through `apply_group_policy()`.
4. Scheduler webhook jobs bypass chat dispatch; raw targets send configured content directly with optional weather appended, while compose targets call `WebhookComposerAgent`.

Keep deterministic guards outside the LLM when they protect product behavior, such as silent group collection and group capability restrictions.

## Group Policy

Group messages are saved before any reply decision. Non-trigger messages stop after persistence and cleanup. Allowed triggers enter `GroupMentionAgent`; training and meal requests are rejected in group context.

Rules:
- Empty group voice recognition returns `empty_content` and is not saved.
- Missing `chat_id` returns `missing_chat_id` and is not saved.
- Summary/weather/simple-QA triggers may reply.
- Poll (create/vote/view/end) and translate triggers route to their respective nodes.
- Unsupported group requests should not reach private tools.
- `apply_group_policy()` owns deterministic trigger classification. `dispatch_message()` passes `group_category` to `GroupMentionAgent`, whose classifier only runs when the agent is called without a preclassified category.

## Private Tool-Calling Pattern

Replyable private messages enter `PrivateButlerAgent`. It owns the LangGraph `ToolNode` loop and exposes existing capabilities as tools instead of duplicating business logic.

Rules:
- Tools read `db`, `user_id`, `chat_type`, and `chat_id` from LangGraph config, not from model-supplied arguments.
- Tool functions return short text; they do not return `AgentResponse` objects.
- Existing domain agents remain the source of truth for summary and reminder workflows.
- Group non-trigger messages stay outside private tool calling and are collected silently.
- Do not add or modify test files unless the user explicitly asks for tests, except when an approved implementation plan explicitly requires test changes.

## Weather Tool Pattern

`src.weather` owns weather lookup. `WeatherService` extracts a location/date from the user text, calls Open-Meteo geocoding and forecast APIs, then returns a `WeatherReport`. Agent-specific tool wrappers live in the agent package that owns the tool-calling loop.

Rules:
- Private chat defines and registers `query_weather` in `src/agents/private_butler/tools.py` with the rest of the private tools.
- Group @ weather triggers bind `query_weather` from `src/agents/group_mention/tools.py` in a restricted ToolNode loop, while unsupported private capabilities remain blocked before tool execution.
- Scheduler webhook raw composition uses target-level `weather_query` and calls `WeatherService` directly before appending `format_weather_report()` to the fixed `message`. Compose targets may still use the `src/agents/webhook_composer/tools.py` wrapper in a small ToolNode loop.
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
- Hybrid retrieval stays inside `KnowledgeService`: existing keyword scoring, SQLite FTS, and local hashing embeddings are merged into one score before returning `KnowledgeChunkResult`.
- `src/knowledge/embedding.py` is intentionally local and deterministic so tests and local development do not need live embedding API calls.
- Local imports use the installable `butler-ingest-knowledge` command. `scripts/ingest_knowledge.py` remains as a compatibility wrapper.

## Scheduler Package Pattern

- `src/scheduler/models.py` defines `WebhookSchedulerTarget`.
- `src/scheduler/config.py` validates and loads target JSON.
- `src/scheduler/client.py` owns Enterprise WeChat webhook HTTP delivery.
- `src/scheduler/manager.py` owns APScheduler lifecycle and jobs.
- `src/scheduler/__init__.py` only re-exports the stable public API.

## Testing Patterns

- Tests should not require real DeepSeek calls.
- Use `conftest.py` fixtures such as `mock_llm` and isolated async DB setup.
- Prefer focused module tests plus callback/scheduler smoke tests when adding behavior.
- Graph agents are tested through `handle()`, the same interface used by scene dispatch and scheduler composition.

## Shared Utility Pattern

For single-step LLM operations that don't need state, persistence, or multi-step routing, place a plain async function in a shared module under `src/agents/` rather than creating a full agent package.

- Example: `src/agents/translate.py` exports `translate_text(text, target_lang, llm)`.
- Both `PrivateButlerAgent` (as a LangChain tool) and `GroupMentionAgent` (as a graph node) call the same function.
- No state TypedDict, no graph compilation, no agent class.

Use this pattern when the operation is a pure LLM transformation. Use the full agent pattern (state + nodes + graph + handle) when the operation needs DB access, multi-step workflow, or conditional routing.

## Chat-Based Knowledge Ingestion Pattern

The `add_to_knowledge` tool allows users to add content to the knowledge base directly from chat, without CLI access.

Rules:
- Tool is defined in both `private_butler/tools.py` and `group_mention/tools.py` with the same name and signature.
- Private chat tool sets `scope_type="user"`, `scope_id=user_id`; group chat tool sets `scope_type="group"`, `scope_id=chat_id`.
- Source is synthetic: `f"chat://{chat_type}/{user_id}"` for traceability.
- Tool calls `KnowledgeService.ingest()` which handles SHA-256 dedup and Chroma indexing.
- Domain defaults to `"qa"`; title defaults to first 40 chars of content if not provided.

## Chroma Integration Pattern

`ChromaStore` wraps `chromadb.PersistentClient` for embedded vector storage. Used by `KnowledgeService` for chunk embeddings.

Rules:
- `ChromaStore()` initializes at module level in `main.py` as a singleton, same pattern as `LLMClient`.
- `index_chunks()` is called during `ingest()` with batch-embedded vectors from `EmbeddingService.batch_embed()`.
- `query()` includes metadata filtering for scope/domain permissions, replacing the old SQLite JOIN approach.
- `KnowledgeService.__init__(chroma_store=None)` — when `None`, Chroma path is silently skipped (backward compat).
- Data directory `chroma_data/` is git-ignored; migration from SQLite vectors via `butler-migrate-to-chroma`.

## Side-Path Async Extraction Pattern

Memory profile extraction runs as a fire-and-forget async task after the main reply is generated.

Rules:
- `PrivateButlerAgent.handle()` calls `asyncio.create_task(_extract_fragments_side_path(...))` after `memory.save_exchange()` and before `return`.
- `_extract_fragments_side_path()` creates its own DB session via `db_session_factory()` — never reuses the request session.
- Three guard layers: `try/except` at session open, extraction call, and write+commit.
- Extraction pre-filter (`_should_extract`) skips messages without personal signals before any LLM call.
- Full trace logging with `[trace:sidepath]` prefix including stage timings.

## RAG Two-Stage Retrieval Pattern

`KnowledgeService.search()` now implements coarse retrieval → fine re-ranking.

Rules:
- `llm` parameter is optional (keyword, default `None`). When `None`, falls back to coarse scores only.
- Coarse retrieval runs 2 paths: Chroma vector (ANN) + SQLite FTS (keyword). Each returns up to 20 results, merged and deduped by chunk_id.
- Re-ranking uses `reranker.rerank_chunks()` which calls LLM with a pointwise scoring prompt (0-10 scale).
- `llm` is passed by the calling agent from `configurable["llm"]`.
- All traces logged with `[trace:search]` prefix: query, user, result count, source titles with scores.
