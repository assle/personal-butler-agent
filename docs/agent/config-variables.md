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
| `WEATHER_TIMEOUT_SECONDS` | No | `8` | Open-Meteo geocoding/forecast HTTP timeout in seconds |
| `DASHSCOPE_API_KEY` | No | `""` | 阿里云百炼 DashScope API key，用于 Qwen3-Embedding 语义向量模型。不配则使用本地字符 n-gram 哈希嵌入 |

## Local Development

Create `.env` from `.env.example` and fill in a real key only on the local machine.

Example shape:

```env
DEEPSEEK_API_KEY=sk-your-actual-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite+aiosqlite:///butler.db
WEATHER_TIMEOUT_SECONDS=8
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
- 入站方式：企业微信通过 HTTP POST 回调公网 URL
- 消息可靠性：回调路由按 `msgid` 幂等落库，便于去重和失败追踪
- 回复方式：通过消息里的临时 `response_url` 被动回复
- 主动推送：主动群推送通过企业微信群机器人 webhook 独立完成

## APScheduler 定时推送

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SCHEDULER_TARGETS_FILE` | No | `""` | 企业微信群 webhook 定时推送目标 JSON 文件路径。设置后按文件中每个群的独立 cron 启动 APScheduler job |

当前 URL 回调模式下，主动推送使用企业微信群机器人 webhook。推荐设置 `SCHEDULER_TARGETS_FILE`，文件中每个群拥有独立 `cron`、`webhook_url` 和 `message`。当前本地配置只有一个目标群：`宇宙幽默帝国`。`name` 是内部稳定标识；`display_name` 是私聊确认和提醒列表展示给用户看的群名；`mode` 可选 `raw` 或 `compose`：`raw` 原样发送固定 `message`，`compose` 保留旧的 LLM 生成正文；`weather_query` 仅支持 `raw`，存在时会在定时触发时直接查询天气并追加到 `message` 后，一次性推送。同一个 target 也可配置 `aliases` 供提醒解析使用，例如把“宇宙幽默帝国”映射到内部标识 `cosmic-humor-empire`；`mention_user_overrides` 是可选兜底，用于回调 `from.userid` 与 webhook `<@userid>` 不一致时覆盖。真实 webhook 地址视为密钥，不提交到仓库；仓库只保留 `config/scheduler_targets.example.json` 模板，真实文件建议命名为 `config/scheduler_targets.local.json`。

示例:

```env
SCHEDULER_TARGETS_FILE=config/scheduler_targets.local.json
```

```json
[
  {
    "name": "cosmic-humor-empire-morning",
    "display_name": "宇宙幽默帝国",
    "cron": "0 9 * * *",
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...",
    "mode": "raw",
    "message": "早上好，今天记得看一下今日重点。",
    "weather_query": "今天杭州天气",
    "aliases": ["宇宙幽默帝国"],
    "mention_user_overrides": {
      "callback_userid": "webhook_mention_userid"
    },
    "enabled": true
  }
]
```

私聊创建提醒时，默认使用企业微信回调 `from.userid` 作为群 webhook markdown 中的 `<@userid>`。只有实际联调发现 @ 不到人时，才需要在对应 target 的 `mention_user_overrides` 中配置覆盖关系。

私聊提醒示例：

```text
创建提醒，今天19:10分在宇宙幽默帝国提醒我该健身了
```

确认回复会显示 `display_name` 和用户本地时区，而不是内部 `name` 或 UTC：

```text
已创建提醒 #1：健身提醒
目标群：宇宙幽默帝国
提醒对象：@LuZhenDong
下次触发：2026-06-04 19:10（Asia/Shanghai）
```

如果生产日志出现 `GET /`、`GET /health`、`GET /v1/models` 等 404，这通常是公网探测请求命中了未注册路径，不是 scheduler 配置触发的定时推送失败，详见 `docs/agent/troubleshooting.md`。

## Change Guidance

- Add new environment variables to `Settings` in `src/config.py`.
- Update `.env.example`, this file, and config tests together.
- Keep secrets out of logs, tests, docs, and committed files.
- Prefer explicit config fields over reading `os.environ` directly in business logic.
