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

## WeChat Work Self-Built App

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `WECHAT_CORP_ID` | No | `""` | Enterprise CorpID for message encryption/decryption |
| `WECHAT_TOKEN` | No | `""` | Callback URL verification Token |
| `WECHAT_ENCODING_AES_KEY` | No | `""` | 43-char Base64 AES key for encrypting/decrypting messages |
| `WECHAT_AGENT_ID` | No | `""` | Self-built app AgentID |

When `WECHAT_CORP_ID` and `WECHAT_TOKEN` are both set, the `/api/wechat/callback` route is registered. The callback uses **passive encrypted XML reply** (5-second timeout applies).

```env
WECHAT_CORP_ID=ww1234567890abcdef
WECHAT_TOKEN=YourRandomToken123
WECHAT_ENCODING_AES_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WECHAT_AGENT_ID=1000005
```

## WeChat Work Intelligent Robot

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `WECHAT_ROBOT_TOKEN` | No | `""` | Intelligent robot callback Token |
| `WECHAT_ROBOT_ENCODING_AES_KEY` | No | `""` | 43-char Base64 AES key for robot message crypto |

When `WECHAT_ROBOT_TOKEN` is set, the `/api/wechat/robot/callback` route is registered. The robot callback uses **active reply via `response_url` POST** (no 5-second timeout). The `receiveid` for crypto is empty string `""` (not CorpID).

```env
WECHAT_ROBOT_TOKEN=YourRobotToken
WECHAT_ROBOT_ENCODING_AES_KEY=YourRobotEncodingAESKey
```

Key differences from self-built app:
- Message format: intelligent-robot-specific JSON (`from.userid`, `text.content`, `chatid`, `response_url`)
- Reply mechanism: POST JSON to `response_url` (only `markdown` and `template_card` msgtypes supported — `text` returns errcode 40008)
- Crypto receiveid: `""` (empty string) instead of CorpID

## WeChat Work Group Bot Webhook

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `WECHAT_WEBHOOK_URL` | No | `""` | Group bot webhook URL for proactive push |

When set, a `WechatWebhookClient` instance is created at app startup. Note: the client is instantiated but not yet called — proactive push scheduling (APScheduler + agent integration) is deferred work (see upgrade-roadmap §3.1).

```env
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxx
```

## Change Guidance

- Add new environment variables to `Settings` in `src/config.py`.
- Update `.env.example`, this file, and config tests together.
- Keep secrets out of logs, tests, docs, and committed files.
- Prefer explicit config fields over reading `os.environ` directly in business logic.
