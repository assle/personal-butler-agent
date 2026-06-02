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
- 主动推送：当前不启动 WebSocket，因此 `aibot_send_msg` 和 APScheduler 主动推送暂不可用

## APScheduler 定时推送

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SCHEDULER_CRON` | No | `""` | Cron 表达式，定义调度频率（例：`0 9 * * 1-5` 表示工作日 9:00） |
| `SCHEDULER_TARGET_TYPE` | No | `"single"` | 推送目标类型，支持 `\|` 分隔多个值：`single`（单聊）/ `group`（群聊） |
| `SCHEDULER_TARGET_ID` | No | `""` | 推送目标 ID，支持 `\|` 分隔多个值。单聊时为 `userid`，群聊时为 `chatid`，按位置与 TARGET_TYPE 配对 |
| `SCHEDULER_MESSAGE` | No | `""` | 定时触发消息文本，支持 `\|` 分隔多个值。单值共享所有目标，多值时须与目标数一致 |
| `SCHEDULER_INTENT` | No | `""` | 可选，支持 `\|` 分隔多个值。有值走指定 agent，空位由 IntentRouter 自动判定（规则 → LLM → unknown/QA 兜底）。全空时所有目标均自动路由 |

所有四个字段 `TARGET_TYPE`、`TARGET_ID`、`MESSAGE`、`INTENT` 均使用 `|` 分隔，按位置配对。单值格式（无 `|`）保持向前兼容。

当前 URL 回调模式不启动 WebSocket，因此即使 `SCHEDULER_CRON`、`SCHEDULER_TARGET_ID` 已设置，应用也不会启动 APScheduler 主动推送。后续如恢复定时提醒，需要重新设计独立主动发送通道。

```env
# 单目标（与原有格式兼容）
SCHEDULER_CRON=0 9 * * 1-5
SCHEDULER_TARGET_TYPE=single
SCHEDULER_TARGET_ID=AssLe
SCHEDULER_MESSAGE=早安！今天我该做什么训练？
SCHEDULER_INTENT=

# 多目标 + 独立消息 + 混合指定/自动 intent
SCHEDULER_CRON=0 9 * * *
SCHEDULER_TARGET_TYPE=single|single|group
SCHEDULER_TARGET_ID=AssLe|ZhangSan|chatid123456
SCHEDULER_MESSAGE=今日训练建议|今天吃什么？|总结一下最近群聊重点
SCHEDULER_INTENT=today_plan||summarize_group
```

## Change Guidance

- Add new environment variables to `Settings` in `src/config.py`.
- Update `.env.example`, this file, and config tests together.
- Keep secrets out of logs, tests, docs, and committed files.
- Prefer explicit config fields over reading `os.environ` directly in business logic.
