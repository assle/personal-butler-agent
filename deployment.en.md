# Deployment Guide

[中文](deployment.md)

This project now uses the WeChat Work intelligent robot URL callback only. The old self-built app callback (`/api/wechat/callback`) and `WECHAT_*` callback variables have been removed.

## Environment

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

## Local

```bash
# Install dependencies
uv sync

# Run database migrations (required before first start)
alembic upgrade head

# Start the application
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

The app no longer exposes a local debug/dev message API. Configure the WeChat Work intelligent robot callback URL through HTTPS tunneling or production HTTPS.

> **Note**: PostgreSQL must be running with the database and user created before starting. See "PostgreSQL Local Setup" below.

## PostgreSQL Local Setup

On macOS with Homebrew:

```bash
# Install PostgreSQL 16
brew install postgresql@16

# Start and enable at boot
brew services start postgresql@16

# Create the application database and user
/opt/homebrew/opt/postgresql@16/bin/psql -h localhost -p 5432 postgres -c \
  "CREATE ROLE butler WITH LOGIN PASSWORD 'butler' CREATEDB;"

# Create application and test databases
for db in butler butler_test; do
  PGPASSWORD=butler /opt/homebrew/opt/postgresql@16/bin/createdb \
    -h localhost -p 5432 -U butler "$db"
done
```

PostgreSQL 16 on Homebrew is keg-only — binaries are at `/opt/homebrew/opt/postgresql@16/bin/`. Add to PATH if needed:

```bash
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
```

### SQLite for Local Development

If you don't have PostgreSQL installed, override `DATABASE_URL` to use SQLite:

```env
DATABASE_URL=sqlite+aiosqlite:///butler.db
DATABASE_REQUIRE_MIGRATIONS=false
```

SQLite mode does not require `alembic upgrade head`; tables are created automatically on startup.

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
