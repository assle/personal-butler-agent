# Personal Butler Agent Instructions

<!-- Keep this file and CLAUDE.md byte-for-byte identical. -->
<!-- Template 2 style: concise root guidance plus on-demand project memory docs. -->

## Project Overview

- Name: Personal Butler Agent
- Stack: Python 3.13+, FastAPI, LangChain, LangGraph, langchain-openai, SQLAlchemy 2 async, SQLite, Pydantic v2, uv, pytest
- Purpose: AI personal butler for WeChat Work style natural-language workflows: fitness logging and plans, meal planning, group-chat summaries, and personalized Q&A.
- Runtime entry: `src.main:app`
- Current interfaces: `POST /api/debug/message` for local debug; `GET/POST /api/wechat/callback` for WeChat Work self-built app message routing.

## Build, Test & Verify

- Install dependencies: `uv sync`
- Run dev server: `uv run uvicorn src.main:app --host 0.0.0.0 --port 8000`
- Run all tests: `DEEPSEEK_API_KEY=test uv run pytest -q`
- Run focused tests: `DEEPSEEK_API_KEY=test uv run pytest tests/test_fitness.py -v`
- Test API manually after starting server:
  `curl -X POST http://localhost:8000/api/debug/message -H "Content-Type: application/json" -d '{"user_id":"assle","message":"打卡 今天练胸 卧推80kg5组8次"}'`

## Code Style & Conventions

- Follow existing Python style in `src/` and `tests/`; keep changes small and local.
- Use async SQLAlchemy sessions for database work. Do not introduce sync DB access.
- Keep Pydantic request/response schemas in `src/schemas/`; keep ORM models in `src/models/`.
- Preserve the current agent boundary: intent routing chooses an intent, AgentRegistry resolves to a graph agent, handle() builds state and runs the StateGraph, returning `AgentResponse`.
- New agents follow the pattern: `state.py` (TypedDict) + `nodes.py` (async node functions) + `graph.py` (StateGraph assembly + agent class).
- Prefer deterministic rules for stable intent matches, then LLM fallback for ambiguous messages.
- Keep tests isolated from real DeepSeek calls by using mock LLM clients and `DEEPSEEK_API_KEY=test`.
- All functions and methods must include Chinese comments describing: (1) what the function does, (2) input parameters, (3) return value. Every `.py` file must start with a Chinese comment block explaining the file's purpose and overall workflow.

## Architecture

- `src/main.py`: FastAPI app, lifespan DB initialization, singleton wiring, AgentRegistry registration.
- `src/router/`: API routes — debug message endpoint and conditional WeChat callback router.
- `src/wechat/`: WeChat Work integration — AES-256-CBC crypto, XML message parsing, group bot webhook push client.
- `src/intent/`: rule-first intent classification with LLM fallback.
- `src/agents/`: business agents for fitness, summary, meal, and Q&A — each a LangGraph StateGraph package.
- `src/agents/registry.py`: central intent-to-agent mapping; new agents register here.
- `src/graph/`: shared graph utilities, MemorySaver checkpoint instance.
- `src/db/`: async SQLAlchemy engine, session factory, declarative base.
- `src/models/`: SQLite ORM models for training records, user preferences, and group chat messages.
- `src/llm/`: LangChain ChatOpenAI wrapper pointed at DeepSeek.
- `tests/`: pytest coverage for schemas, config, DB, intent routing, agents, and API smoke flow.

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

All files are part of the shared project documentation. If you update one root entry file, update the other so `CLAUDE.md` and `AGENTS.md` remain identical.

### Memory Workflow

1. Session start: read `docs/agent/active-context.md` for continuity.
2. Before implementation: read `docs/agent/patterns.md` and relevant source files.
3. Before architecture changes: read `docs/agent/decisions.md`.
4. When debugging: read `docs/agent/troubleshooting.md`, then verify against current code.
5. After significant work: update the relevant `docs/agent/*.md` file only if the user asked for project documentation to be maintained or the change would otherwise make the docs misleading.

---

## Current MVP Baseline

- Implemented: debug endpoint, rule-first intent router, LangChain ChatOpenAI LLM fallback, four LangGraph StateGraph agents (Fitness/Summary/Meal/QA), AgentRegistry, LangGraph MemorySaver checkpointing, SQLite persistence, WeChat Work self-built app callback (encryption + routing), group chat summarization (passive collection + trigger detection), and group bot webhook push client.
- Deferred: APScheduler reminders and digests, persistent conversation memory (SqliteSaver), async customer-service message reply, and RAG.
- Latest verified baseline: `DEEPSEEK_API_KEY=test uv run pytest -q` reports 68 passing tests.
