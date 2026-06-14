# Personal Butler Agent — Project Brief

## Capability Status

| Capability | Status | Evidence |
|---|---|---|
| WeChat Work intelligent robot callback | Implemented | `tests/test_wecom_*.py`, callback route |
| Idempotent inbox (msgid dedup) | Implemented | `src/wechat/callback_inbox.py`, inbound message tests |
| Scene Agent (private/group ReAct) | Implemented | `tests/test_butler_agent.py`, private/group graph |
| Chroma-backed RAG with workspace scopes | Implemented | `tests/test_knowledge_service.py` |
| 15-tool private butler agent | Implemented | `src/agents/private_butler/tools.py` |
| Durable research DAG (plan -> steps -> synthesis -> review) | Implemented (Week 1) | `tests/test_research_pipeline.py`, `tests/integration/test_research_step_claims.py` |
| Citation quality gate with bounded repair | Implemented (Week 1) | `tests/test_research_quality_gate.py`, `tests/test_research_citation_reviewer.py` |
| Retry/circuit breaker/lease recovery | Implemented (Week 2) | `tests/test_research_retry_policy.py`, `tests/test_research_circuit_breaker.py`, `tests/test_research_watchdog.py` |
| Deterministic evaluation (24 cases) | Implemented (Week 3) | `tests/fixtures/research_eval_cases.json`, `artifacts/evaluation/2026-06-interview-baseline.json` |
| Worker-count benchmark (1/3/5) | Implemented (Week 3) | `artifacts/benchmarks/2026-06-interview-baseline.json` |
| PostgreSQL + Alembic (production) | Implemented | `alembic/versions/`, `src/db/migrations.py` |
| SQLite (local dev fallback) | Implemented | `DATABASE_REQUIRE_MIGRATIONS=false` |
| SSRF and prompt-injection protection | Implemented | `tests/test_research_security.py`, `src/research/web/url_policy.py` |
| Research Skills (YAML frontmatter) | Implemented | `research_skills/general/SKILL.md` |
| MCP provider runtime | Reserved | `src/research/providers/mcp.py` (contract only, no transport) |
| Live production metrics | Not claimed | Benchmark uses controlled PostgreSQL, not production |
| Model fine-tuning | Out of scope | Not claimed |
| Docker deployment | Future work | Local `uv run uvicorn` only |
| CI pipeline | Implemented | `.github/workflows/test.yml` (unit + integration) |

## Architecture Summary

- **Scene Agents**: LangGraph StateGraph for private chat (ReAct + 15 tools) and group mention
- **Research Pipeline**: PostgreSQL DAG with Taskiq workers, multi-agent pipeline (Supervisor -> Specialists -> Synthesizer -> Reviewer -> Quality Gate)
- **Governance**: Workspace isolation, permission engine (5-rule priority chain), HookBus (7 lifecycle events)
- **Reliability**: Exponential backoff retry, Redis circuit breaker, lease watchdog, bounded repair

## Key Design Decisions

| Decision | Rationale |
|---|---|
| PostgreSQL authoritative, Redis transport | DB owns all state; queue carries only task IDs, preventing split-brain |
| LangGraph for scene agents, durable DAG for research | Scene agents need low-latency ReAct loops; research needs checkpointable, resumable long-running workflows |
| Dynamic tools default-denied | Registered tools checked by PermissionEngine at execution time; prevents unintended capability exposure |
| Delivery separate from research execution | Failed delivery preserves a completed report; failed research never enqueues delivery; isolation prevents cascading failures |
