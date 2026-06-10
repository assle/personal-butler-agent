# Personal Butler Agent

[中文](README.md)

AI personal butler for WeChat Work intelligent robot workflows. The current runtime uses scene-specific agents for private chat, group mentions, and scheduled group webhook composition.

## Current Interfaces

| Interface | Path / Config | Purpose |
|----------|----------------|---------|
| Intelligent robot URL callback | `GET/POST /api/wechat/aibot/callback` | WeChat Work URL verification, message callbacks, and passive `response_url` replies |
| Enterprise WeChat group webhook push | `SCHEDULER_TARGETS_FILE` | APScheduler reads JSON targets, sends raw content or generated markdown, and pushes to group webhooks |

The app no longer exposes a local debug/dev message API. Use HTTPS tunneling or production HTTPS to test the real WeChat Work callback.

## Architecture

```text
WeChat Work intelligent robot callback
  -> callback_router decrypts, verifies, and records by msgid
  -> callback_handler normalizes to InboundMessage
  -> dispatch_message routes by scene
       ├─ single -> PrivateButlerAgent
       │            └─ LangGraph tool calling -> Summary / Knowledge / Web Search / Weather / Reminder
       └─ group  -> apply_group_policy stores group messages and checks triggers
                    └─ GroupMentionAgent -> group summary / live weather / simple QA / rejection

APScheduler
  -> SchedulerManager
  -> raw composition or WebhookComposerAgent
  -> WebhookPushClient sends to Enterprise WeChat group webhook
```

## Stack

| Component | Choice |
|-----------|--------|
| Runtime | Python 3.13+ |
| Web framework | FastAPI |
| Agent framework | LangGraph + LangChain |
| LLM | langchain-openai -> DeepSeek/OpenAI-compatible API |
| WeChat crypto | cryptography (AES-256-CBC) |
| ORM | SQLAlchemy 2 async + aiosqlite |
| Validation | Pydantic v2 |
| Scheduler | APScheduler |
| Package manager | uv |
| Tests | pytest + pytest-asyncio |

## Capabilities

| Scene | Agent | Capabilities |
|-------|-------|--------------|
| Private chat | `PrivateButlerAgent` | Natural conversation, text summaries, local knowledge retrieval, web search, weather, and group webhook reminders |
| Group mention | `GroupMentionAgent` | Group summaries, live weather, and lightweight QA; unavailable capabilities such as training and meal plans are rejected |
| Scheduled group push | `SchedulerManager` / `WebhookComposerAgent` | Sends fixed content, appends weather, or generates markdown from target instructions |

## Project Layout

```text
personal_butler_agent/
├── src/
│   ├── main.py                  # FastAPI app, singleton wiring, callback route, scheduler
│   ├── config.py                # .env settings
│   ├── messaging/               # InboundMessage, group policy, scene dispatch
│   ├── wechat/                  # URL callback, crypto, inbox, response_url replies
│   ├── scheduler/               # Target model/config, webhook client, scheduler manager
│   ├── cli/                     # Installable maintenance commands
│   ├── agents/
│   │   ├── private_butler/      # Private-chat tool-calling controller
│   │   ├── group_mention/       # Restricted group mention agent
│   │   ├── webhook_composer/    # Scheduler-only markdown composer
│   │   ├── fitness/             # Legacy source package, not wired at runtime
│   │   ├── summary/
│   │   ├── meal/                # Legacy source package, not wired at runtime
│   │   └── qa/                  # Legacy standalone QA agent
│   ├── knowledge/
│   ├── memory/
│   ├── models/
│   ├── schemas/
│   ├── llm/
│   └── db/
├── tests/
├── docs/agent/
├── i18n/                        # Historical translation snapshots
├── config/scheduler_targets.example.json
├── deployment-guide.en.md
├── 部署指南.md
├── AGENTS.md
├── CLAUDE.md
└── README.md
```

## Quick Start

```bash
uv sync
cp .env.example .env
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

Run tests:

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Import a local knowledge document:

```bash
uv run butler-ingest-knowledge notes.md --scope-type public --domain qa
```

Configure this callback URL in WeChat Work intelligent robot admin:

```text
https://<your-domain>/api/wechat/aibot/callback
```

See [deployment-guide.en.md](deployment-guide.en.md) for production setup.

## Configuration

Base `.env`:

```env
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite+aiosqlite:///butler.db

WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WECOM_AIBOT_TOKEN=your-callback-token
WECOM_AIBOT_ENCODING_AES_KEY=your-43-char-encoding-aes-key
```

Scheduled group webhook push:

```env
SCHEDULER_TARGETS_FILE=config/scheduler_targets.local.json
```

Target JSON example:

```json
[
  {
    "name": "cosmic-humor-empire-morning",
    "display_name": "宇宙幽默帝国",
    "cron": "0 9 * * *",
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_WEBHOOK_KEY",
    "mode": "raw",
    "message": "Good morning. Review today's priorities.",
    "weather_query": "today Hangzhou weather",
    "aliases": ["宇宙幽默帝国"],
    "mention_user_overrides": {},
    "enabled": true
  }
]
```

The current local setup has one target group: `宇宙幽默帝国`. `name` is the stable internal identifier; `display_name` is shown in private-chat confirmations and reminder lists; `mode` selects raw or LLM-composed content; `weather_query` is available only in `raw` mode and appends a live weather result; `aliases` help parse natural-language targets.

Private-chat reminder example:

```text
创建提醒，今天19:10分在宇宙幽默帝国提醒我该健身了
```

The confirmation reply shows the user-facing group name and local time:

```text
已创建提醒 #1：健身提醒
目标群：宇宙幽默帝国
提醒对象：@LuZhenDong
下次触发：2026-06-04 19:10（Asia/Shanghai）
```

Do not commit real `.env` values or real group webhook URLs.

## Message Rules

| Message | Behavior |
|---------|----------|
| Private text | Enters `PrivateButlerAgent`; the model decides whether to answer directly or call tools |
| Private voice | Uses WeChat Work recognition text and follows private text flow; empty recognition is ignored |
| Normal group message | Saved to `group_messages`; no reply |
| Group summary/weather/simple question | Saved, then routed to `GroupMentionAgent` |
| Group training/meal/private tasks | Short rejection, asking the user to switch to private chat |
| Other message types | Unsupported-message reply |

## Development Notes

- Read `docs/agent/active-context.md`, `docs/agent/patterns.md`, and relevant source files before code changes.
- New cross-scene behavior should first choose an owner: private chat, group mention, or scheduler composition.
- New domain agents should keep the `state.py` + `nodes.py` + `graph.py` + `handle()` structure.
- Never commit real API keys, real `.env` files, or real group webhook URLs.
