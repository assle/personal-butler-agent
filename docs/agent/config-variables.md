# Config Variables

Configuration is loaded by `src/config.py` with Pydantic Settings. The app reads `.env` by default.

## Required Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DEEPSEEK_API_KEY` | Yes | None | API key for DeepSeek/OpenAI-compatible chat calls |
| `DEEPSEEK_BASE_URL` | No | `https://api.deepseek.com` | Base URL for the OpenAI-compatible provider |
| `DEEPSEEK_MODEL` | No | `deepseek-chat` | Chat model used by `LLMClient` |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///butler.db` | SQLAlchemy async database URL |

## Local Development

Create `.env` from `.env.example` and fill in a real key only on the local machine.

Example shape:

```env
DEEPSEEK_API_KEY=sk-your-actual-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite+aiosqlite:///butler.db
```

Do not commit `.env` or real API keys.

## Tests

Use a placeholder key for tests:

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Tests should mock LLM calls and should not depend on the placeholder key being valid.

## Change Guidance

- Add new environment variables to `Settings` in `src/config.py`.
- Update `.env.example`, this file, and config tests together.
- Keep secrets out of logs, tests, docs, and committed files.
- Prefer explicit config fields over reading `os.environ` directly in business logic.
