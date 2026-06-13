# Personal Butler Agent Instructions

<!-- Keep this file and AGENTS.md byte-for-byte identical. -->
<!-- Template 2 style: concise root guidance plus on-demand project memory docs. -->

## Project Overview

- Name: Personal Butler Agent
- Stack: Python 3.13+, FastAPI, LangChain, LangGraph, langchain-openai, SQLAlchemy 2 async, PostgreSQL (production) / SQLite (dev), asyncpg, Alembic, ChromaDB, Taskiq, Redis, Pydantic v2, uv, pytest
- Purpose: AI personal butler for WeChat Work natural-language workflows: private Q&A, group-chat interactions, weather lookup, reminders, polls, translation, personalized memory, async long-form research, RAG knowledge retrieval, and scheduled group pushes.
- Runtime entry: `src.main:app` (FastAPI producer); optional `taskiq worker src.research.broker:broker src.research.tasks` for async research
- Current interfaces: `GET/POST /api/wechat/aibot/callback` for WeChat Work intelligent robot URL callback routing (inbound); scheduler jobs push to Enterprise WeChat group webhooks (outbound group); WeChat custom-application API for proactive private delivery (outbound private, research complete notifications)

## Build, Test & Verify

For build, test, and verification steps, see `deployment.en.md` in the project root.

## Code Style & Conventions

- Follow existing Python style in `src/`; keep changes small and local.
- Preserve the current scene-agent boundary: URL callback messages normalize to `InboundMessage`, scene dispatch chooses private chat or group policy, scene agents call domain StateGraph agents as needed, returning `AgentResponse`.
- Do not add or modify test files unless the user explicitly asks for tests.
- All functions and methods must include Chinese comments describing: (1) what the function does, (2) input parameters, (3) return value. Every `.py` file must start with a Chinese comment block explaining the file's purpose and overall workflow.

For detailed patterns (async DB, agent structure), load `docs/agent/patterns.md`.

## Architecture

- `src/main.py`: FastAPI app, lifespan DB initialization, singleton wiring for domain agents, scene agents, and optional async research.
- `src/messaging/`: normalized inbound messages, group message policy, and private/group scene dispatch.
- `src/wechat/`: WeChat Work intelligent robot integration (URL callback crypto, callback router, inbox, response_url reply) and custom-application client (access token cache, ID conversion, proactive private messaging).
- `src/agents/`: scene agents (`private_butler`, `group_mention`, `webhook_composer`) plus domain agents for summary, reminder, poll, memory, and shared utilities (translate).
- `src/governance/`: workspace membership resolution, permission engine, and research lifecycle hooks.
- `src/research/`: async research subsystem — task lifecycle, broker, queue, planning, approval, budgeting, supervisor, specialists, tool registry, evidence, synthesis, citation review, quality gate, repair, delivery, and step execution.
- `src/research/supervisor/`: LLM structured-output planner with validation
- `src/research/specialists/`: knowledge and web retrieval specialists
- `src/research/tools/`: governed tool registry with permission checks
- `src/research/evidence.py`: normalized evidence dedup and persistence
- `src/research/execution.py`: step executor with evidence writing
- `src/research/sources.py`: workspace-authorized source gateway
- `src/research/synthesis/`: evidence-grounded report synthesis with claim-evidence bindings
- `src/research/review/`: independent citation review and validation
- `src/research/quality.py`: quality gate and bounded repair coordinator
- `src/memory/`: conversation memory persistence and retrieval (sliding window + LLM-compressed summary).
- `src/reminders/`: reminder lifecycle service — natural-language parsing, CRUD, and expiry.
- `src/scheduler/`: APScheduler lifecycle, config loading, and webhook HTTP client for outbound group pushes.
- `src/graph/`: shared graph utilities, MemorySaver checkpoint instance.
- `src/db/`: async SQLAlchemy engine, session factory, declarative base.
- `src/models/`: PostgreSQL/SQLite ORM models for messaging, conversation memory, knowledge, reminders, polls, group webhooks, workspace governance, research tasks, execution DAG, evidence, quality claims, and user memories.
- `src/llm/`: LangChain ChatOpenAI wrapper pointed at DeepSeek.
- `src/knowledge/`: Knowledge base RAG, `EmbeddingService` (DashScope Qwen3-Embedding API with local hashing fallback), `ChromaStore` embedded vector DB, parsers (PDF/web).
- `src/search/`: web search service (DuckDuckGo), configurable and disabled by default.
- `src/weather/`: weather lookup service (Open-Meteo geocoding and forecast APIs).
- `src/schemas/`: shared Pydantic response schemas (`AgentResponse`).
- `src/cli/`: CLI entry points for knowledge ingestion and Chroma migration.
- `tests/`: existing pytest coverage.

---

## Core Rules

**Investigation & accuracy:**
- Never speculate about code you have not read. Read files and use `rg` for usages before making claims.
- If the user references a file, read it before answering.
- If uncertain, say so and propose how to verify. Do not fabricate APIs, paths, or behavior.

**Scope discipline:**
- Do what has been asked; nothing more, nothing less.
- When intent is ambiguous, default to research and recommendations. Only edit when explicitly asked.
- Make only requested changes. Do not refactor adjacent code or create abstractions for one use.
- Follow scoping words like "only", "just", and "exactly" literally.

**Verification & safety:**
- Before declaring done, re-check requirements, run relevant tests, and state what changed and what could not be verified.
- After any code change that adds/removes directories, agents, models, or dependencies: verify CLAUDE.md Architecture and Purpose sections still match current code.
- Ask before destructive or hard-to-reverse actions: deleting files or branches, force pushes, hard resets, or `--no-verify`.
- Edit existing files in place where practical. Do not create scratch files unless needed, and clean them up.
- Never commit secrets or real `.env` values.

**Efficiency & tools:**
- Parallelize independent reads and searches; serialize dependent steps.
- Use `rg` instead of `grep` and `rg --files` instead of recursive `find` for repo exploration.
- Use structured parsers and project APIs instead of ad hoc text manipulation when reasonable.

---

## Project Memory Docs

Read on demand. Load only the docs relevant to the current task.

| File | Purpose | Read When |
|------|---------|-----------|
| `docs/agent/active-context.md` | Current state, MVP completion, near-term roadmap | At session start or before planning feature work |
| `docs/agent/patterns.md` | Established implementation patterns | Before adding or changing code |
| `docs/agent/decisions.md` | Architecture decisions and constraints | Before design choices or scope changes |
| `docs/agent/troubleshooting.md` | Known issues and proven checks | When debugging failures |
| `docs/agent/config-variables.md` | Environment variables and config behavior | When touching config, LLM, DB, or runtime setup |

| `docs/agent/upgrade-roadmap.md` | Upgrade points and improvement priorities | When planning future work or evaluating technical debt |

> `docs/superpowers/` contains completed historical design documents and implementation plans. Reference only when studying project evolution — skip for everyday tasks.

### Memory Workflow

**Read:**

1. Session start: read `docs/agent/active-context.md` for continuity.
2. Before implementation: read `docs/agent/patterns.md` and relevant source files.
3. Before architecture changes: read `docs/agent/decisions.md`.
4. When debugging: read `docs/agent/troubleshooting.md`, then verify against current code.
5. When touching config, LLM, or DB: read `docs/agent/config-variables.md`.

**Write — update the matching doc after:**

| Action | Update |
|--------|--------|
| Added a new agent, route, or capability | `docs/agent/active-context.md` — add to "What Is Implemented" |
| Completed an item from upgrade-roadmap | `docs/agent/upgrade-roadmap.md` — remove or mark done |
| Made or changed an architecture decision | `docs/agent/decisions.md` — add or update ADR |
| Found and fixed a reproducible issue | `docs/agent/troubleshooting.md` — add symptom + check + fix |
| Added or changed env vars or config fields | `docs/agent/config-variables.md` — update tables and examples |
| Established a reusable implementation pattern | `docs/agent/patterns.md` — add pattern section |
| Modified CLAUDE.md | Copy to `AGENTS.md` to keep them byte-for-byte identical |
| Added, removed, or renamed a directory, dependency, or runtime component | CLAUDE.md — update Architecture and Purpose sections to reflect current project structure |

**After writing docs:** Verify CLAUDE.md's agent list, model names, and directory structure match the current codebase. Docs that drift from reality are worse than no docs.
