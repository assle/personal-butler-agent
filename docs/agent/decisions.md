# Architecture Decisions

> Recorded architecture decisions and rationale. Load before making design choices or scope changes.

## ADR-001: Single-Process FastAPI MVP

The MVP is a single-process FastAPI application. It avoids Redis, Celery, Kafka, Docker, and Kubernetes until the product needs them.

Reasoning:
- The current goal is a local, understandable personal-butler demo.
- A single process keeps debugging and deployment simple.
- Future scheduling can start with APScheduler before introducing external workers.

## ADR-002: SQLite as the Memory Layer

The MVP stores training records and user preferences in SQLite through async SQLAlchemy.

Reasoning:
- SQLite is enough for local single-user or small private use.
- SQLAlchemy keeps the model layer portable if the app later moves to PostgreSQL.
- JSON preferences allow new domains to add namespaces without immediate migrations.

## ADR-003: Rule-First Intent Routing

Intent routing checks deterministic rules before calling the LLM fallback.

Reasoning:
- Common commands should be cheap, stable, and testable.
- LLM fallback handles natural-language variation without making every route probabilistic.
- Invalid LLM output must degrade to `unknown` safely.

## ADR-004: Agent-per-Domain Boundaries

Fitness, summary, meal, and Q&A behavior live in separate agent packages, each implemented as a LangGraph `StateGraph`.

Reasoning:
- Each agent can own domain prompts, DB access, validation, and response shaping.
- StateGraph nodes isolate responsibilities further: extraction, validation, persistence, and formatting are separate functions.
- Tests stay focused by domain.
- Future modules can follow the same interface (state + nodes + graph + registry) without rewriting the dispatcher.

## ADR-005: Debug Endpoint Before WeChat Work Integration

The MVP keeps `POST /api/debug/message` as the first integration surface.

Reasoning:
- It makes local and automated tests independent of WeChat Work callback signing and network setup.
- Real WeChat Work callback support should be added beside this route first, not by deleting the debug route.

## ADR-006: DeepSeek Through LangChain ChatOpenAI

The LLM wrapper uses `langchain_openai.ChatOpenAI` with configurable DeepSeek-compatible base URL and model.

Reasoning:
- It keeps provider details centralized in `src/llm/client.py`.
- Tests can mock the wrapper without touching business agents.
- Future provider changes should happen behind the wrapper.
- LangChain's ChatOpenAI provides a standard interface that integrates with LangGraph's ecosystem.

## ADR-007: LangGraph StateGraph for Agent Orchestration

Each agent is implemented as a LangGraph `StateGraph` rather than a linear class method chain.

Reasoning:
- StateGraph provides a first-class state machine that natively supports multi-step workflows, conditional routing, error recovery, and checkpointing.
- Node-per-responsibility decomposition makes agents easier to test, extend, and reason about.
- LangGraph's `MemorySaver` checkpointing gives multi-turn conversation memory with near-zero custom code.
- LangGraph is the current industry standard for agent development and aligns with interview expectations.
- Simple agents (QA, Summary) stay simple with a linear graph. Complex agents (Fitness) gain conditional routing between sub-intents.
- The `handle()` interface remains identical — callers (routes, tests, schedulers) are unaffected.

## ADR-008: Separate Intelligent Robot Callback from Self-Built App Callback

The intelligent robot API callback (`/api/wechat/robot/callback`) is implemented as a separate router and route from the self-built app callback (`/api/wechat/callback`).

Reasoning:
- **Different message format**: The intelligent robot sends JSON with nested fields (`from.userid`, `text.content`, `chatid`, `response_url`), while the self-built app sends XML/flat JSON (`FromUserName`, `Content`, `ChatId`). Attempting to share a parser would create fragile branching logic.
- **Different reply mechanism**: The robot uses active reply via `response_url` POST (JSON), while the self-built app uses passive encrypted XML reply. These are fundamentally different code paths.
- **Different crypto receiveid**: The robot uses `""` (empty string), the self-built app uses CorpID. Sharing the decrypt call with different receiveid values is bug-prone.
- **Independent config**: Separate `WECHAT_ROBOT_TOKEN`/`WECHAT_ROBOT_ENCODING_AES_KEY` from `WECHAT_CORP_ID`/`WECHAT_TOKEN`/`WECHAT_ENCODING_AES_KEY`. Each can be enabled independently.
- **Independent failure domains**: A bug in the robot callback won't break the self-built app callback, and vice versa.
- **response_url msgtype constraint**: The robot's `response_url` only supports `markdown` and `template_card` msgtypes — not `text`. This constraint only applies to the robot router.

## ADR-009: Sliding Window + LLM-Compressed Conversation Memory

Conversation memory uses a 6-turn (12-message) sliding window in prompt context, with older messages compressed into a single summary string by LLM and persisted to SQLite.

Reasoning:
- **Sliding window (recent messages in prompt)**: Keeps the most recent exchanges in full fidelity so agents can reference specific user statements and assistant replies. 6 turns is small enough to fit in context, large enough to cover a coherent topic thread.
- **LLM-compressed summary**: Older messages beyond the window are not discarded — they are periodically compressed into a one-sentence summary by a lightweight LLM call. This preserves key facts and preferences from earlier exchanges without consuming token budget.
- **SQLite persistence**: Summaries and messages survive process restarts, unlike LangGraph's in-memory `MemorySaver` which is only for single-session graph checkpointing.
- **Automatic compression trigger**: When a user exceeds 24 total messages, the oldest 12 are compressed. This keeps the message table bounded without manual cleanup.
- **Intent-conditional memory**: Not all agents/contexts benefit from context. `log_training` (one-shot record) and Summary agents (independent per call) skip memory loading. QA, Fitness `today_plan`, and Meal always load it.

Trade-off: The compression prompt is a separate LLM call, adding latency and cost per ~12 exchanges. For the current single-user MVP scale this is negligible. At higher throughput, compression could be deferred to a background job.

Trade-off: The two routers (`src/wechat/router.py` and `src/wechat/robot_router.py`) share some structural similarity (GET URL verification, POST decrypt + signature check). The shared crypto and message-building utilities in `src/wechat/crypto.py` and `src/wechat/messages.py` prevent code duplication at the lower layers while keeping the routing logic separate where it diverges.
