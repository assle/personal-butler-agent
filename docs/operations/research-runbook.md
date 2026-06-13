# Research Harness Operations Runbook

## Process Topology
- FastAPI (1 process): handles submissions, approvals, status queries
- Taskiq workers (1-3 processes): planning, steps, synthesis, validation, delivery
- PostgreSQL: authoritative state
- Redis: task queue + circuit breaker state

## Startup
```bash
uv run alembic upgrade head
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
uv run taskiq worker --ack-type when_executed --workers 3 --max-async-tasks 4 src.research.broker:broker src.research.tasks
```

## Health Checks
- PostgreSQL: `pg_isready -U butler`
- Redis: `redis-cli ping`
- Alembic: `uv run alembic check`
- Queue: check Redis Stream `butler-research` length

## Common Issues
See `docs/agent/troubleshooting.md` for detailed troubleshooting.
- Stuck steps: watchdog recovers expired leases every minute
- Circuit open: check Redis `research:circuit:*` keys; resets after configured seconds
- Approval backlog: tasks in `awaiting_approval` status
