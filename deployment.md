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
