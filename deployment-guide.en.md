# Deployment Guide

[中文](部署指南.md)

This project now uses the WeChat Work intelligent robot URL callback only. The old self-built app callback (`/api/wechat/callback`) and `WECHAT_*` callback variables have been removed.

## Environment

```env
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite+aiosqlite:///butler.db

WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WECOM_AIBOT_TOKEN=your-callback-token
WECOM_AIBOT_ENCODING_AES_KEY=your-43-char-encoding-aes-key
```

## Local

```bash
uv sync
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

Debug endpoint:

```bash
curl -X POST http://127.0.0.1:8000/api/debug/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"assle","message":"今天练什么"}'
```

## Production

Run uvicorn on loopback only:

```bash
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

Expose HTTPS with Caddy:

```caddy
butler.assle.online {
    reverse_proxy 127.0.0.1:8000
}
```

Configure the callback URL in WeChat Work intelligent robot admin:

```text
https://butler.assle.online/api/wechat/aibot/callback
```

## Verify

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
curl -i https://butler.assle.online/api/wechat/aibot/callback
```

The plain GET without WeChat signature should not succeed as a verification request; it only checks that the route is reachable through HTTPS.
