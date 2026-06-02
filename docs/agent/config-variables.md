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

## 智能机器人长连接模式

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `WECOM_AIBOT_BOT_ID` | No | `""` | 智能机器人 BotId，用于长连接鉴权 |
| `WECOM_AIBOT_SECRET` | No | `""` | 智能机器人 Secret，用于长连接鉴权 |

当 `WECOM_AIBOT_BOT_ID` 和 `WECOM_AIBOT_SECRET` 同时设置时，应用启动时建立 WebSocket 长连接到企业微信智能机器人网关。长连接模式无需公网 IP/域名/SSL、无需消息加解密，支持消息收发和主动推送（`aibot_send_msg`）。

```env
WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WECOM_AIBOT_SECRET=your-bot-secret
```

与回调模式的关键差异：
- 连接方式：WebSocket 长连接替代 HTTP 回调
- 消息格式：企业微信智能机器人 JSON WebSocket 协议
- 回复方式：通过 WebSocket 连接下发消息，支持 `aibot_send_msg` 主动推送
- 部署：无需公网地址，无需 AES 加解密

## 企业微信服务端 API

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `WECOM_CORP_SECRET` | No | `""` | 自建应用 Secret，用于调用 `/cgi-bin/gettoken` 获取 access_token，进而查询用户详细信息（姓名/部门/头像等） |

当 `WECOM_CORP_SECRET` 和 `WECHAT_CORP_ID` 同时设置时，应用启动时初始化 `WeComUserService`，在 Bot 消息处理流程中自动查询用户信息并注入 agent 上下文（user_name / user_department），本地 SQLite 缓存 TTL 24h。

```env
WECOM_CORP_SECRET=your-app-secret
```

## APScheduler 定时推送

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SCHEDULER_CRON` | No | `""` | Cron 表达式，定义调度频率（例：`0 9 * * 1-5` 表示工作日 9:00） |
| `SCHEDULER_TARGET_TYPE` | No | `"single"` | 推送目标类型：`single`（单聊）或 `group`（群聊） |
| `SCHEDULER_TARGET_ID` | No | `""` | 推送目标 ID：单聊时为 `userid`，群聊时为 `chatid` |
| `SCHEDULER_MESSAGE` | No | `""` | 定时触发消息文本，发送给 LLM 进行意图路由和 agent 处理 |
| `SCHEDULER_INTENT` | No | `""` | 可选，指定使用的 intent，绕过 intent 路由。为空时自动路由 |

当 `SCHEDULER_CRON` 和 `SCHEDULER_MESSAGE` 同时设置且长连接模式已启用时，应用启动时注册 APScheduler 定时任务，按 cron 表达式周期触发 LLM 推送。

```env
SCHEDULER_CRON=0 9 * * 1-5
SCHEDULER_TARGET_TYPE=single
SCHEDULER_TARGET_ID=AssLe
SCHEDULER_MESSAGE=早安！今天我该做什么训练？
SCHEDULER_INTENT=
```

## Change Guidance

- Add new environment variables to `Settings` in `src/config.py`.
- Update `.env.example`, this file, and config tests together.
- Keep secrets out of logs, tests, docs, and committed files.
- Prefer explicit config fields over reading `os.environ` directly in business logic.
