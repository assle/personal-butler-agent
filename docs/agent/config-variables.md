# Config Variables

> Environment variables, WeChat Work config, and change guidance. Load when modifying config, LLM, DB, or runtime setup.

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

## 智能机器人 URL 回调模式

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `WECOM_AIBOT_BOT_ID` | No | `""` | 智能机器人 BotID，用于消息体 `aibotid` 校验 |
| `WECOM_AIBOT_TOKEN` | No | `""` | 智能机器人 URL 回调 Token，用于签名校验 |
| `WECOM_AIBOT_ENCODING_AES_KEY` | No | `""` | 智能机器人 URL 回调 EncodingAESKey，用于消息加解密 |

当 `WECOM_AIBOT_TOKEN` 和 `WECOM_AIBOT_ENCODING_AES_KEY` 同时设置时，应用注册 `GET/POST /api/wechat/aibot/callback`。企业微信后台 URL 配置为：

```text
https://<你的域名>/api/wechat/aibot/callback
```

URL 回调模式需要公网 HTTPS、Token 和 EncodingAESKey。应用收到消息后先写入 `inbound_messages`，再后台处理并通过消息体中的 `response_url` 发送 markdown 回复。

```env
WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WECOM_AIBOT_TOKEN=your-callback-token
WECOM_AIBOT_ENCODING_AES_KEY=your-43-char-encoding-aes-key
```

关键差异：
- 入站方式：企业微信通过 HTTP POST 回调公网 URL，而不是应用主动维持 WebSocket
- 消息可靠性：回调路由按 `msgid` 幂等落库，便于去重和失败追踪
- 回复方式：通过消息里的临时 `response_url` 被动回复
- 主动推送：URL 回调模式不启动 WebSocket；主动群推送通过企业微信群机器人 webhook 独立完成

## APScheduler 定时推送

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SCHEDULER_TARGETS_FILE` | No | `""` | 企业微信群 webhook 定时推送目标 JSON 文件路径。设置后按文件中每个群的独立 cron 启动 APScheduler job |

当前 URL 回调模式下，主动推送使用企业微信群机器人 webhook。推荐设置 `SCHEDULER_TARGETS_FILE`，文件中每个群拥有独立 `cron`、`webhook_url`、`message` 和 `intent`。真实 webhook 地址视为密钥，不提交到仓库；仓库只保留 `config/scheduler_targets.example.json` 模板，真实文件建议命名为 `config/scheduler_targets.local.json`。

示例:

```env
SCHEDULER_TARGETS_FILE=config/scheduler_targets.local.json
```

```json
[
  {
    "name": "fitness-group",
    "cron": "0 9 * * *",
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...",
    "message": "今日训练建议",
    "intent": "butler",
    "enabled": true
  }
]
```

如果生产日志出现 `GET /`、`GET /health`、`GET /v1/models` 等 404，这通常是公网探测请求命中了未注册路径，不是 scheduler 配置触发的定时推送失败，详见 `docs/agent/troubleshooting.md`。

## Change Guidance

- Add new environment variables to `Settings` in `src/config.py`.
- Update `.env.example`, this file, and config tests together.
- Keep secrets out of logs, tests, docs, and committed files.
- Prefer explicit config fields over reading `os.environ` directly in business logic.
