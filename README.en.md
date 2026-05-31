# Personal Butler Agent

[中文](README.md)

An AI personal butler system based on WeChat Work — manage fitness, meals, group chat summaries, and daily tasks through natural language interaction.

## Architecture Overview

```
User → WeChat Work Self-Built App → FastAPI Callback → Intent Router (Rules + LLM)
                                                           ↓
                                                     Agent Registry
                                                           ↓
                                           ┌───────┬───────┼───────┬────────┐
                                           ↓       ↓       ↓       ↓        ↓
                                        Fitness Summary  Meal     QA   (Extensible)
                                           ↓       ↓       ↓       ↓
                                           └───────┴───────┴───────┘
                                                     │
                                               StateGraph Engine
                                            (LangGraph + MemorySaver)
                                                     │
                                                 SQLite Database
                                                     │
                                           ┌─────────┴──────────┐
                                           ↓                    ↓
                                    Self-Built App         Group Bot
                                    Private Reply         Webhook Push
```

**Seven-layer Design:**

| Layer | Technology | Description |
|----|------|------|
| Self-Built App | WeChat Work | Interaction entry point, receives user commands |
| Group Bot | Webhook | Announcements, daily reports, notifications pushed to groups |
| Agent Orchestration | LangGraph StateGraph | State machine driven, multi-step reasoning, conditional routing |
| LLM | LangChain ChatOpenAI → DeepSeek | Intent understanding, content generation, structured extraction |
| Rule Engine | Keyword Matching | Deterministic routing, zero cost |
| Memory Layer | SQLite + MemorySaver | Persistent preferences/training records + multi-turn conversation checkpoints |
| Scheduler | APScheduler | Scheduled task driver (daily reports, reminders) |

## Tech Stack

| Component | Choice |
|------|------|
| Runtime | Python 3.13+ |
| Web Framework | FastAPI |
| Agent Framework | LangGraph + LangChain |
| LLM | langchain-openai → DeepSeek API |
| WeChat Work Crypto | cryptography (AES-256-CBC) |
| ORM | SQLAlchemy 2.0 (async) + aiosqlite |
| Data Validation | Pydantic v2 |
| Scheduled Tasks | APScheduler |
| Package Manager | uv |
| Testing | pytest + pytest-asyncio |

## Project Structure

```
personal_butler_agent/
├── src/
│   ├── main.py              # FastAPI app entry + AgentRegistry + conditional WeChat Work route startup
│   ├── config.py            # .env configuration loader (LLM / DB / WeChat Work)
│   ├── router/
│   │   └── debug.py         # POST /api/debug/message (local debug endpoint)
│   ├── wechat/              # WeChat Work integration module
│   │   ├── crypto.py        # AES-256-CBC encrypt/decrypt + SHA1 signature verification
│   │   ├── messages.py      # XML parse/build + message dataclasses
│   │   ├── webhook.py       # Group bot webhook push client
│   │   └── router.py        # GET/POST /api/wechat/callback
│   ├── intent/
│   │   ├── rules.py         # Keyword rule matching
│   │   └── router.py        # Rule-first + LLM fallback routing
│   ├── agents/
│   │   ├── registry.py      # intent → agent central registry
│   │   ├── base.py          # BaseGraphAgent abstract base class
│   │   ├── fitness/
│   │   │   ├── state.py     # FitnessState TypedDict
│   │   │   ├── nodes.py     # Node functions (extract/validate/persist/generate...)
│   │   │   └── graph.py     # StateGraph assembly + FitnessAgent class
│   │   ├── summary/         # Same pattern as above
│   │   ├── meal/            # Same pattern as above
│   │   └── qa/              # Same pattern as above
│   ├── graph/
│   │   └── memory.py        # LangGraph MemorySaver shared instance
│   ├── models/
│   │   ├── training.py      # Training record ORM
│   │   ├── preference.py    # User preference ORM (JSON)
│   │   └── group_message.py # Group chat message ORM
│   ├── schemas/
│   │   ├── request.py       # Request schemas
│   │   └── response.py      # Response schemas
│   ├── llm/
│   │   └── client.py        # ChatOpenAI wrapper (DeepSeek-compatible)
│   └── db/
│       ├── base.py          # SQLAlchemy DeclarativeBase
│       └── session.py       # Async engine + session factory + get_db dependency injection
├── tests/                   # 68 tests
├── docs/
│   ├── agent/               # Project memory docs (active-context / patterns / decisions / upgrade-roadmap)
│   └── superpowers/
│       ├── specs/           # Design documents
│       └── plans/           # Implementation plans
├── i18n/                    # Internationalized documentation
├── pyproject.toml
├── .env.example
├── CLAUDE.md                # AI assistant project instructions
├── 部署指南.md               # Complete dev/production deployment guide
└── README.md
```

## Quick Start

### Dev Environment (Local)

```bash
# 1. Clone the project
git clone https://github.com/assle/personal-butler-agent.git
cd personal-butler-agent

# 2. Install dependencies
uv sync
uv pip install pytest pytest-asyncio httpx

# 3. Configure .env
cp .env.example .env
# Edit .env, fill in DEEPSEEK_API_KEY=sk-xxxxxxxx

# 4. Start dev server
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000

# 5. Test call
curl -X POST http://localhost:8000/api/debug/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"assle","message":"打卡 今天练胸 卧推80kg5组8次"}'
```

### Production Environment (Cloud Server)

See [`部署指南.md`](部署指南.md) — complete steps from scratch using uv + Caddy + systemd.

## API Endpoints

### POST /api/debug/message

Local debug endpoint, simulates WeChat Work message callbacks. Always available, no WeChat Work configuration required.

**Request:**

```json
{
  "user_id": "assle",
  "message": "打卡 今天练胸 卧推80kg5组8次",
  "timestamp": "2026-05-29T16:30:00"
}
```

| Field | Type | Required | Description |
|------|------|------|------|
| user_id | string | Yes | User identifier |
| message | string | Yes | Message text |
| timestamp | datetime | No | Message time |

**Response:**

```json
{
  "intent": "log_training",
  "confidence": 1.0,
  "response": "已记录 2 条训练：卧推、飞鸟",
  "data": { "records": [{ "muscle_group": "胸", "exercise": "卧推", ... }] }
}
```

| Field | Type | Description |
|------|------|------|
| intent | string | Recognized intent |
| confidence | float | Confidence 0.0-1.0 |
| response | string | Reply text |
| data | object | Structured data (optional) |

### GET/POST /api/wechat/callback

WeChat Work self-built app callback. **Only registered when both `WECHAT_CORP_ID` and `WECHAT_TOKEN` are configured in `.env`.**

| Method | Purpose | Description |
|------|------|------|
| GET | URL Verification | Triggered when configuring callback URL in WeChat Work admin; verifies signature and decrypts echostr |
| POST | Message Reception | Triggered when users send messages in WeChat Work; decrypt → intent routing → agent reply → encrypt and return |

For detailed design, see `docs/superpowers/specs/2026-05-30-wechat-work-integration-design.md`.

## Supported Intents

| Intent | Trigger | Function |
|------|----------|------|
| `log_training` | "打卡 练胸..." / "记录训练" | Natural language training record logging |
| `today_plan` | "今天练什么" / "训练建议" | Generate training plan based on history and preferences |
| `summarize_text` | "帮我总结..." / "summary" | Structured private chat text summarization |
| `summarize_group` | "@bot 总结一下群消息" | Structured group chat history summarization |
| `make_meal_plan` | "今天吃什么" / "食谱" | Generate full-day meal plan with nutrition estimates |
| `qa` | Default fallback | Personalized Q&A |
| `unknown` | Unrecognizable | Returns prompt message |

**Intent routing strategy:** Keyword rules first (deterministic, zero cost). Unmatched messages fall back to LangChain ChatOpenAI calling DeepSeek for classification.

## Agent Architecture

Each Agent is a LangGraph `StateGraph` composed of three parts:

| File | Responsibility |
|------|------|
| `state.py` | TypedDict defining graph state |
| `nodes.py` | Single-responsibility async node functions (extract / validate / generate / format, etc.) |
| `graph.py` | StateGraph assembly + Agent class (provides `handle()` entry point) |

**FitnessAgent Example:**

```
__start__
    │
[path_condition] ← Conditional routing by intent
 /               \
log_training     today_plan
 extract         fetch_history
 validate        fetch_prefs
 persist         generate
 format_log      format_plan
    \               /
   __end__        __end__
```

Adding a new Agent: create `state.py` + `nodes.py` + `graph.py` → register in `src/main.py` via `agent_registry.register(intent, agent)`.

## WeChat Work Integration

### Self-Built App Callback

- User sends message to self-built app in WeChat Work → WeChat Work POSTs encrypted XML to `/api/wechat/callback`
- Encryption: AES-256-CBC + PKCS#7 padding + SHA1 signature verification
- Callback URL, Token, and EncodingAESKey are configured in WeChat Work admin console

### Group Bot Webhook

- `WechatWebhookClient` pushes text/markdown messages to group webhook URLs via HTTP POST
- Client instance auto-created when `WECHAT_WEBHOOK_URL` is configured

### Configuration Variables

| Variable | Required | Description |
|------|------|------|
| `WECHAT_CORP_ID` | Callback required | Enterprise CorpID |
| `WECHAT_TOKEN` | Callback required | URL verification Token |
| `WECHAT_ENCODING_AES_KEY` | Callback required | Message encrypt/decrypt AES key |
| `WECHAT_AGENT_ID` | No | Application AgentId |
| `WECHAT_WEBHOOK_URL` | Push required | Group bot webhook URL |

## Database

SQLite local file storage with three core tables:

**training_records** — Training records

| Column | Type | Description |
|----|------|------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT NOT NULL | User identifier |
| date | TEXT NOT NULL | Training date YYYY-MM-DD |
| muscle_group | TEXT NOT NULL | Target muscle group |
| exercise | TEXT NOT NULL | Exercise name |
| sets | INTEGER NOT NULL | Number of sets |
| reps | INTEGER NOT NULL | Reps per set |
| weight_kg | REAL | Weight |
| created_at | TEXT | Creation timestamp |

**user_preferences** — User preferences

| Column | Type | Description |
|----|------|------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT NOT NULL UNIQUE | User identifier |
| preferences | TEXT NOT NULL | JSON preferences (namespace-organized) |

**group_messages** — Group chat messages

| Column | Type | Description |
|----|------|------|
| id | INTEGER PK | Auto-increment |
| chat_id | TEXT NOT NULL INDEXED | Group chat ID |
| user_id | TEXT NOT NULL | Sender identifier |
| content | TEXT NOT NULL | Message content |
| create_time | INTEGER NOT NULL | Message timestamp |

Preferences JSON structure is extensible — new modules add their own namespace:

```json
{
  "fitness": {
    "body": { "height_cm": null, "weight_kg": null, "age": null },
    "goal": "general_fitness",
    "level": "beginner"
  },
  "meal": {
    "calorie_target": null,
    "diet_type": "balanced",
    "allergies": []
  }
}
```

## Running Tests

```bash
# Run all tests (68)
DEEPSEEK_API_KEY=test uv run pytest -q

# Run a single module
DEEPSEEK_API_KEY=test uv run pytest tests/test_fitness.py -v

# Run WeChat Work module tests
DEEPSEEK_API_KEY=test uv run pytest tests/test_wechat_crypto.py tests/test_wechat_messages.py -v
```

## Implemented Features

The following features have complete end-to-end workflows, from user input to app response with zero errors and correct results.

---

### 1. Self-Built App Private Chat Q&A

Users send messages to the self-built app in WeChat Work. The app processes them through: decrypt → intent recognition → LLM processing → encrypt reply.

**Usage:**

1. Create a self-built app in WeChat Work admin console, set callback URL to `https://<your-domain>/api/wechat/callback`
2. Fill in WeChat Work config in `.env`:
   ```bash
   WECHAT_CORP_ID=ww1234567890abcdef      # Enterprise CorpID
   WECHAT_TOKEN=your_token_here           # Callback Token
   WECHAT_ENCODING_AES_KEY=your_aes_key   # 43-char EncodingAESKey
   ```
3. Restart the service and send messages to the self-built app in WeChat Work

**Five integrated intents and usage examples:**

#### 1.1 Training Logging (`log_training`)

Record fitness training data using natural language descriptions of multiple exercises, weights, sets, and reps.

| Trigger | Example Message |
|----------|----------|
| Contains "打卡" | `打卡 今天练胸 卧推80kg5组8次 飞鸟15kg4组12次` |
| Contains "记录训练" | `记录训练 深蹲100kg5x5 腿举200kg3x10` |

#### 1.2 Training Plan Suggestions (`today_plan`)

Generate personalized daily training plans based on historical training records and user preferences.

| Trigger | Example Message |
|----------|----------|
| Contains "训练" + query intent | `今天练什么` |
| Contains "计划" | `给我一个今天的训练计划` |
| Contains "建议" + training | `训练建议 我想练背` |

#### 1.3 Text Summary (`summarize_text`)

Summarize user-provided text into structured format: discussion topic, key conclusions, action items, and decisions.

| Trigger | Example Message |
|----------|----------|
| Contains "总结" or "摘要" | `总结下面这段话：张三说今天开会讨论了项目进度...` |
| Contains "概括" | `概括一下：<long text>` |

#### 1.4 Group Chat Summary (`summarize_group`)

Trigger group chat summarization with @mention + summary keywords. All group messages are passively collected; only trigger messages generate replies.

| Trigger | Example Message |
|----------|----------|
| Group chat + summary keywords | `@bot 总结一下群消息` |
| | `@bot 摘要` / `@bot 概括` / `@bot 汇总` |

#### 1.5 Meal Planning (`make_meal_plan`)

Generate full-day meal plans with nutrition estimates based on preferences (calorie targets, diet type, allergies).

| Trigger | Example Message |
|----------|----------|
| Contains "吃什么" | `今天吃什么` |
| Contains "食谱" | `给我一份低碳水食谱` |

#### 1.6 Personalized Q&A (`qa`)

When none of the above intents match, messages are routed to free-form Q&A via LLM.

| Trigger | Example Message |
|----------|----------|
| Any message not matching rules above | `我今天的训练量够吗` |

---

### 2. Debug Endpoint (POST /api/debug/message)

Local development HTTP endpoint for testing the full intent routing and agent pipeline without WeChat Work.

**Usage:**

```bash
curl -X POST http://localhost:8000/api/debug/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"assle","message":"打卡 今天练胸 卧推80kg5组8次"}'
```

Supports `chat_type` and `chat_id` fields for simulating group chat scenarios.

### Current Limitations & Next Steps

| Status | Feature | Description |
|------|------|------|
| Implemented | Self-built app private chat Q&A | All intents fully functional |
| Implemented | Debug endpoint | Full local testing capability |
| Implemented | Training data persistence | SQLite storage with history queries |
| Implemented | User preference management | Auto-extract and persist preferences |
| Implemented | Multi-turn conversation memory | MemorySaver checkpointing (in-process, lost on restart) |
| Implemented | Group chat summarization | Passive collection + trigger-based summary |
| Client exists, not wired | Group bot webhook push | `WechatWebhookClient` implemented and tested, not yet connected to agents and scheduler |
| Not implemented | APScheduler scheduled tasks | Daily push, training reminders, etc. |
| Not implemented | Persistent conversation memory | MemorySaver → SqliteSaver, retain context across restarts |
| Not implemented | Async customer service reply | Overcome WeChat Work passive reply 5-second timeout |
| Not implemented | RAG knowledge base | Enhanced answers with external knowledge |

See [`docs/agent/upgrade-roadmap.md`](docs/agent/upgrade-roadmap.md) for details.

## License

MIT
