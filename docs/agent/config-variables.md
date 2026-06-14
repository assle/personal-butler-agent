# Config Variables

> Environment variables, WeChat Work config, and change guidance. Load when modifying config, LLM, DB, or runtime setup.

Configuration is loaded by `src/config.py` with Pydantic Settings. The app reads `.env` by default.

## Required Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `DEEPSEEK_API_KEY` | Yes | None | API key for DeepSeek/OpenAI-compatible chat calls |
| `DEEPSEEK_BASE_URL` | No | `https://api.deepseek.com` | Base URL for the OpenAI-compatible provider |
| `DEEPSEEK_MODEL` | No | `deepseek-chat` | Chat model used by `LLMClient` |
| `DATABASE_URL` | No | `postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler` | SQLAlchemy async database URL |
| `DATABASE_POOL_SIZE` | No | `10` | PostgreSQL 常驻连接数 |
| `DATABASE_MAX_OVERFLOW` | No | `20` | PostgreSQL 临时溢出连接数 |
| `DATABASE_REQUIRE_MIGRATIONS` | No | `true` | 启动时要求数据库 Alembic 版本已达到 HEAD |
| `DEFAULT_WORKSPACE_ID` | No | `default` | 首次迁移时创建的默认工作空间 ID |
| `DEFAULT_WORKSPACE_NAME` | No | `Default Workspace` | 默认工作空间名称 |
| `DEFAULT_WORKSPACE_OWNER_OPEN_USERID` | Research setup | `""` | 启动时加入默认工作空间的企业微信用户 ID，留空则不自动授权 |
| `WEATHER_TIMEOUT_SECONDS` | No | `8` | Open-Meteo geocoding/forecast HTTP timeout in seconds |
| `DASHSCOPE_API_KEY` | No | `""` | 阿里云百炼 DashScope API key，用于 Qwen3-Embedding 语义向量模型。不配则使用本地字符 n-gram 哈希嵌入 |

## Local Development

Create `.env` from `.env.example` and fill in a real key only on the local machine.

Example shape:

```env
DEEPSEEK_API_KEY=sk-your-actual-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_REQUIRE_MIGRATIONS=true
DEFAULT_WORKSPACE_ID=default
DEFAULT_WORKSPACE_NAME=Default Workspace
DEFAULT_WORKSPACE_OWNER_OPEN_USERID=your-wecom-userid
WEATHER_TIMEOUT_SECONDS=8
```

If you need to use SQLite for local development (e.g., no PostgreSQL installed), override `DATABASE_URL`:

```env
DATABASE_URL=sqlite+aiosqlite:///butler.db
DATABASE_REQUIRE_MIGRATIONS=false
```

Do not commit `.env` or real API keys.

## PostgreSQL Local Setup

On macOS with Homebrew:

```bash
# 安装 PostgreSQL 16
brew install postgresql@16

# 启动并设为开机自启
brew services start postgresql@16

# 创建应用数据库和用户
/opt/homebrew/opt/postgresql@16/bin/psql -h localhost -p 5432 postgres -c \
  "CREATE ROLE butler WITH LOGIN PASSWORD 'butler' CREATEDB;"

# 创建应用数据库和测试数据库
for db in butler butler_test; do
  PGPASSWORD=butler /opt/homebrew/opt/postgresql@16/bin/createdb \
    -h localhost -p 5432 -U butler "$db"
done
```

PostgreSQL 16 on Homebrew is keg-only — binaries are at `/opt/homebrew/opt/postgresql@16/bin/`. Add to PATH if needed:

```bash
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
```

Key connection details after setup:

| Item | Value |
|------|-------|
| Host | `127.0.0.1:5432` |
| User / Password | `butler` / `butler` |
| App database | `butler` |
| Test database | `butler_test` |
| SQLAlchemy URL | `postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler` |
| Test DB URL | `postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test` |

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

## 异步研究任务

Phase 1 异步研究：私聊提交问题，Worker 在独立进程中生成 LLM 初稿，通过企微自建应用主动推送给用户。默认关闭。

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `RESEARCH_ENABLED` | No | `false` | 启用异步研究任务 |
| `REDIS_URL` | If enabled | `redis://127.0.0.1:6379/0` | Redis 连接地址 |
| `RESEARCH_QUEUE_NAME` | If enabled | `butler-research` | Redis Stream 队列名称 |
| `RESEARCH_MAX_ROUNDS` | If enabled | `4` | 研究最大迭代轮次 |
| `RESEARCH_TIMEOUT_SECONDS` | If enabled | `300` | 单次研究硬超时（秒） |
| `RESEARCH_MAX_STEPS` | No | `12` | 单个研究任务最大步骤数 |
| `RESEARCH_MAX_CONCURRENT_STEPS` | No | `3` | 最大并发研究步骤数 |
| `RESEARCH_SOFT_TOKEN_BUDGET` | No | `15000` | 软 token 预算阈值 |
| `RESEARCH_HARD_TOKEN_BUDGET` | No | `20000` | 硬 token 预算上限 |
| `RESEARCH_SOFT_COST_MICROUNITS` | No | `350000` | 软成本预算阈值 |
| `RESEARCH_HARD_COST_MICROUNITS` | No | `500000` | 硬成本预算上限 |
| `RESEARCH_MAX_REPLANS` | No | `2` | 最大重新规划次数 |
| `RESEARCH_MAX_REPAIR_ROUNDS` | No | `1` | 最大修复轮次 |
| `RESEARCH_STEP_LEASE_SECONDS` | No | `120` | 步骤租约秒数 |
| `RESEARCH_HIGH_COST_APPROVAL_MICROUNITS` | No | `250000` | 高成本审批阈值 |
| `RESEARCH_CIRCUIT_FAILURE_THRESHOLD` | No | `3` | 提供者熔断器连续失败阈值 |
| `RESEARCH_CIRCUIT_OPEN_SECONDS` | No | `60` | 熔断器开启持续时间（秒） |
| `RESEARCH_RETRY_BASE_SECONDS` | No | `1.0` | 指数退避重试基础间隔（秒） |
| `RESEARCH_RETRY_MAX_SECONDS` | No | `30.0` | 指数退避重试最大间隔（秒） |
| `RESEARCH_WEB_FETCH_TIMEOUT_SECONDS` | No | `15` | 安全网页抓取超时（秒） |
| `RESEARCH_WEB_MAX_RESPONSE_BYTES` | No | `2000000` | 网页抓取最大响应字节数 |
| `RESEARCH_WEB_MAX_REDIRECTS` | No | `5` | 网页抓取最大重定向次数 |
| `RESEARCH_WEB_MAX_PAGES_PER_TASK` | No | `20` | 单任务最大网页抓取数 |
| `RESEARCH_MCP_ENABLED` | No | `false` | MCP 动态工具提供者开关（默认关闭） |
| `RESEARCH_RETRY_BASE_SECONDS` | No | `1.0` | 重试指数退避初始秒数 |
| `RESEARCH_RETRY_MAX_SECONDS` | No | `30.0` | 重试最大延迟秒数 |
| `RESEARCH_WEB_FETCH_TIMEOUT_SECONDS` | No | `15` | 网页抓取超时（秒） |
| `RESEARCH_WEB_MAX_RESPONSE_BYTES` | No | `2000000` | 网页抓取最大响应字节 |
| `RESEARCH_WEB_MAX_REDIRECTS` | No | `5` | 网页抓取最大重定向次数 |
| `RESEARCH_WEB_MAX_PAGES_PER_TASK` | No | `20` | 单个任务最大抓取页面数 |

## 企业微信自建应用主动私聊

研究报告投递使用自建应用 API，与智能机器人 URL 回调配置相互独立。

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `WECOM_APP_CORP_ID` | If research | `""` | 自建应用 CorpID |
| `WECOM_APP_SECRET` | If research | `""` | 自建应用 Secret |
| `WECOM_APP_AGENT_ID` | If research | `0` | 自建应用 AgentID |
| `WECOM_APP_CALLBACK_TOKEN` | For callback verification | `""` | 自建应用“接收消息服务器”回调 Token |
| `WECOM_APP_CALLBACK_ENCODING_AES_KEY` | For callback verification | `""` | 自建应用“接收消息服务器”回调 EncodingAESKey |

当 `RESEARCH_ENABLED=true` 时，`WECOM_APP_CORP_ID`、`WECOM_APP_SECRET` 和 `WECOM_APP_AGENT_ID`（>0）为必填。缺失时应用启动报 `RuntimeError`。

这些变量与已退役的 `WECOM_CORP_ID`/`WECOM_CORP_SECRET` 无关。
`WECOM_APP_CORP_ID`、`WECOM_APP_SECRET`、`WECOM_APP_AGENT_ID` 用于主动私聊；
两个 `WECOM_APP_CALLBACK_*` 变量仅用于接收消息服务器 URL 验证。

当 `WECOM_APP_CORP_ID`、`WECOM_APP_CALLBACK_TOKEN` 和
`WECOM_APP_CALLBACK_ENCODING_AES_KEY` 同时配置时，应用注册：

```text
GET/POST /api/wechat/app/callback
```

该接口只用于企业微信后台验证“接收消息服务器 URL”。POST 消息通过验签和解密
后直接返回 `success`，不会写入消息库、不会调用 Agent，也不会改变研究报告的发送
对象。研究报告仍由 `WeComAppMessageClient` 使用自建应用 API 主动私聊任务发起人。

## Change Guidance

- Add new environment variables to `Settings` in `src/config.py`.
- Update `.env.example`, this file, and config tests together.
- Keep secrets out of logs, tests, docs, and committed files.
- Prefer explicit config fields over reading `os.environ` directly in business logic.
