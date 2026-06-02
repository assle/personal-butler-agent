# Personal Butler Agent

[中文](README.md)

AI personal butler for WeChat Work intelligent robot workflows: fitness logging and plans, meal planning, group-chat summaries, personalized Q&A, conversation memory, and Stage 1 SQLite-backed knowledge retrieval.

## Current Interfaces

| Interface | Path | Purpose |
|----------|------|---------|
| Debug API | `POST /api/debug/message` | Local development and automated tests |
| Intelligent robot callback | `GET/POST /api/wechat/aibot/callback` | WeChat Work intelligent robot URL verification and message callbacks |

The old WeChat Work self-built app callback (`/api/wechat/callback`) has been removed.

## Required Configuration

```env
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite+aiosqlite:///butler.db

WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WECOM_AIBOT_TOKEN=your-callback-token
WECOM_AIBOT_ENCODING_AES_KEY=your-43-char-encoding-aes-key
```

Configure this callback URL in WeChat Work intelligent robot admin:

```text
https://<your-domain>/api/wechat/aibot/callback
```

## Run

```bash
uv sync
DEEPSEEK_API_KEY=test uv run pytest -q
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

For production, run uvicorn behind HTTPS reverse proxy such as Caddy:

```text
butler.assle.online {
    reverse_proxy 127.0.0.1:8000
}
```

## Message Flow

```text
WeChat Work intelligent robot
  -> GET/POST /api/wechat/aibot/callback
  -> decrypt and verify callback
  -> store inbound message by msgid
  -> route intent
  -> run LangGraph agent
  -> reply through response_url
```

## Notes

- Inbound messages are persisted in `inbound_messages` before background processing.
- Duplicate callbacks are deduplicated by `msgid`.
- APScheduler proactive push is currently paused because URL callback mode does not start the WebSocket client.
