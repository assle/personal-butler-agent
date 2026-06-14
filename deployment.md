# 部署指南

[English](deployment.en.md)

当前项目只使用企业微信智能机器人 URL 回调。旧自建应用回调 `/api/wechat/callback` 以及 `WECHAT_TOKEN`、`WECHAT_ENCODING_AES_KEY` 等配置已删除。

## 环境变量

```env
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_REQUIRE_MIGRATIONS=true

WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WECOM_AIBOT_TOKEN=your-callback-token
WECOM_AIBOT_ENCODING_AES_KEY=your-43-char-encoding-aes-key
```

## 本地启动

```bash
# 安装依赖
uv sync

# 运行数据库迁移（首次启动前必须执行）
alembic upgrade head

# 启动应用
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

应用不再暴露本地 debug/dev 消息 API。本地调试请通过 HTTPS 隧道或生产 HTTPS 配置企业微信智能机器人 URL 回调。

> **注意**: 启动前需要 PostgreSQL 运行中且已创建数据库和用户。参见下方"PostgreSQL 本地搭建"。

### 启用异步研究

研究功能采用两个独立进程：

1. FastAPI 接收企业微信回调并创建研究任务。
2. Taskiq Worker 从 Redis 取出任务并执行规划、检索、综合、审查和投递。

ZeroNews 等内网穿透只需要把公网 HTTPS 转发到 FastAPI 的
`127.0.0.1:8000`，不需要也不应该暴露 Worker 端口。

确保 `.env` 中已配置：

```env
RESEARCH_ENABLED=true
REDIS_URL=redis://127.0.0.1:6379/0
DEFAULT_WORKSPACE_ID=default
DEFAULT_WORKSPACE_NAME=Default Workspace
DEFAULT_WORKSPACE_OWNER_OPEN_USERID=LuZhenDong
WECOM_APP_CORP_ID=your-corp-id
WECOM_APP_SECRET=your-app-secret
WECOM_APP_AGENT_ID=1000001
WECOM_APP_CALLBACK_TOKEN=后台接收消息服务器页面填写的Token
WECOM_APP_CALLBACK_ENCODING_AES_KEY=后台接收消息服务器页面填写的EncodingAESKey
```

然后分别启动：

```bash
# 进程 1：企业微信回调
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000

# 进程 2：异步研究
uv run taskiq worker --ack-type when_executed \
  --workers 1 --max-async-tasks 4 \
  src.research.broker:broker src.research.tasks
```

PyCharm 当前项目已配置三个运行项：

- `local-butler`：只启动 FastAPI。
- `research-worker`：只启动研究 Worker。
- `local-full-stack`：同时启动上述两个进程，本地联调推荐选择此项。

若运行项没有立即出现在下拉框中，重新打开项目即可。Redis 和 PostgreSQL
仍需作为本机服务提前启动。

研究完成后的主动私聊投递还要求 Taskiq Worker 的公网出口 IP 已加入企业微信
自建应用的可信 IP。HTTPS 内网穿透只负责让企业微信访问 FastAPI 回调，不能满足
出站 API 的可信 IP 要求。若出现 `60020 not allow to access from your ip`，请在
企业微信管理后台更新该自建应用的可信 IP。

没有自有域名时，可使用 ZeroNews 公网 HTTPS 地址完成自建应用回调验证：

1. 在企业微信自建应用中点击“设置接收消息服务器 URL”。
2. URL 填写：

   ```text
   https://<你的 ZeroNews 公网 HTTPS 地址>/api/wechat/app/callback
   ```

3. 在后台页面生成或填写 Token、EncodingAESKey，并把完全相同的值写入 `.env`
   的 `WECOM_APP_CALLBACK_TOKEN`、`WECOM_APP_CALLBACK_ENCODING_AES_KEY`。
4. 重启 FastAPI，确认 ZeroNews 仍转发到 `127.0.0.1:8000`。
5. 回到企业微信后台保存接收消息服务器配置；GET 验证成功后即可配置企业可信 IP。
6. 在本机执行 `curl https://api.ipify.org` 获取 Worker 当前公网出口 IP，将结果填入
   “企业可信 IP”。IP 变化后需要重新更新。

该回调只用于验证配置。研究任务仍由智能机器人私聊发起，研究完成后由自建应用
主动私聊任务发起人，不会发送到群聊。

企业微信私聊提交格式：

```text
深度研究：比较 Taskiq 和 Celery 的适用场景
```

查询格式：

```text
查看研究任务 R20260614-1234ABCD
```

## PostgreSQL 本地搭建

macOS 使用 Homebrew 安装：

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

PostgreSQL 16 on Homebrew is keg-only — binaries are at `/opt/homebrew/opt/postgresql@16/bin/`. Add to PATH if needed：

```bash
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
```

### SQLite 本地开发

如果没有安装 PostgreSQL，可以将 `DATABASE_URL` 覆盖为 SQLite 用于本地开发：

```env
DATABASE_URL=sqlite+aiosqlite:///butler.db
DATABASE_REQUIRE_MIGRATIONS=false
```

SQLite 模式不需要 `alembic upgrade head`，启动时自动建表。

## 生产部署

uvicorn 只监听本机：

```bash
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

用 Caddy 对外提供 HTTPS：

```caddy
butler.assle.online {
    reverse_proxy 127.0.0.1:8000
}
```

企业微信智能机器人后台填写回调 URL：

```text
https://butler.assle.online/api/wechat/aibot/callback
```

## 验证

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
curl -i https://butler.assle.online/api/wechat/aibot/callback
```

不带企业微信签名的普通 GET 不会完成 URL 验证；这里只用于确认 HTTPS 路由可达。
