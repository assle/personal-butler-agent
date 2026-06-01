# Personal Butler Agent MVP Design Spec

## Overview

An MVP personal butler system based on WeChat Work. Users send commands through WeChat Work self-built app, backend Agent handles intent routing, calls business modules, reads/writes SQLite database, generates results, and replies via self-built app private message or group bot webhook push.

## Tech Stack

| Layer | Choice |
|-------|--------|
| Runtime | Python 3.13+ |
| Web Framework | FastAPI |
| ORM | SQLAlchemy + SQLite |
| Data Validation | Pydantic |
| Scheduler | APScheduler (in-memory mode) |
| Package Manager | uv |
| Testing | pytest |
| LLM | DeepSeek API (`deepseek-v4-pro`), OpenAI-compatible client |

**Constraints:** No Redis, Celery, Kafka, Docker, Kubernetes. Single-process deployment.

## Architecture

```
User → WeChat Work Self-Built App → FastAPI Callback → Intent Router
                                                          ↓
                                                ┌─────────┴──────────┐
                                                ↓         ↓          ↓
                                            Fitness   Summary    Meal / QA
                                                ↓         ↓          ↓
                                                └─────────┬──────────┘
                                                          ↓
                                                    SQLite Database
                                                          ↓
                                                ┌─────────┬──────────┐
                                                ↓                    ↓
                                          Self-Built App        Group Bot
                                          Private Reply        Webhook Push
```

Six layers:
- **Self-Built App** = Interaction entry point
- **Group Bot** = Proactive push exit point
- **SQLite** = Memory layer
- **LLM** = Parse and generate layer
- **Rule Engine** = Stable decision layer
- **Scheduler** = Timed trigger

## Project Structure

```
personal_butler_agent/
├── src/
│   ├── __init__.py
│   ├── main.py                # FastAPI app entry point
│   ├── config.py              # .env config loader
│   ├── router/
│   │   ├── __init__.py
│   │   └── debug.py           # POST /api/debug/message
│   ├── intent/
│   │   ├── __init__.py
│   │   ├── router.py          # IntentRouter: rules → LLM fallback
│   │   └── rules.py           # Keyword/regex rule sets
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py            # Agent abstract base class
│   │   ├── fitness.py         # Fitness Agent
│   │   ├── summary.py         # Summary Agent
│   │   ├── meal.py            # Meal Agent
│   │   └── qa.py              # QA Agent
│   ├── models/
│   │   ├── __init__.py
│   │   ├── training.py        # TrainingRecord ORM
│   │   └── preference.py      # UserPreference ORM (JSON preferences)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── request.py         # Pydantic request schemas
│   │   └── response.py        # Pydantic response schemas
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py          # OpenAI-compatible client (DeepSeek)
│   └── db/
│       ├── __init__.py
│       ├── session.py         # Database session factory
│       └── base.py            # SQLAlchemy declarative base
├── tests/
│   ├── __init__.py
│   ├── test_intent.py
│   ├── test_fitness.py
│   ├── test_summary.py
│   ├── test_meal.py
│   └── test_qa.py
├── .env.example
├── .gitignore
├── pyproject.toml
└── uv.lock
```

## Database Design

### training_records

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT NOT NULL | User identifier |
| date | TEXT NOT NULL | Training date YYYY-MM-DD |
| muscle_group | TEXT NOT NULL | Target muscle group |
| exercise | TEXT NOT NULL | Exercise name |
| sets | INTEGER NOT NULL | Number of sets |
| reps | INTEGER NOT NULL | Reps per set |
| weight_kg | REAL | Weight, nullable for bodyweight |
| created_at | TEXT | Creation timestamp |

### user_preferences

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| user_id | TEXT NOT NULL UNIQUE | User identifier |
| preferences | TEXT NOT NULL | JSON blob, namespace-organized |
| created_at | TEXT | Creation timestamp |
| updated_at | TEXT | Last update timestamp |

Default preferences JSON:

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

Preferences are extensible — new modules add their own namespace under the JSON root. No schema migration needed. Pydantic validates known namespaces; unknown namespaces pass through unchanged.

## Intent Router

Two-tier routing: **rules first, LLM fallback.**

```
User Message
  ↓
Rule Layer (rules.py)
  ├── Keyword match hit → return (intent, confidence=1.0)
  └── No match
        ↓
LLM Fallback (router.py)
  └── Send message + intent list to DeepSeek
     → return classification (intent, confidence)
```

### Intent Types

| Intent | Trigger Keywords |
|--------|-----------------|
| `log_training` | 打卡, 记录训练, 练了, 训练 |
| `today_plan` | 今天练什么, 今日计划, 训练建议 |
| `summarize_text` | 总结, summary, 帮我总结 |
| `make_meal_plan` | 食谱, 吃什么, meal plan, 饮食 |
| `qa` | Default fallback for non-empty messages |
| `unknown` | Unrecognizable input |

### LLM Fallback

System prompt lists 6 intents with descriptions. Model returns:

```json
{"intent": "qa", "confidence": 0.85}
```

Hard rule: if LLM returns an intent not in the known list, fallback to `unknown`.

## Fitness Agent

### log_training

User sends natural language → LLM extracts structured data → validate → write to `training_records`.

```
"打卡 今天练胸 卧推80kg5组8次 飞鸟15kg3组12次"
  → LLM extract → [
    {date:"2026-05-29", muscle_group:"胸", exercise:"卧推", sets:5, reps:8, weight_kg:80},
    {date:"2026-05-29", muscle_group:"胸", exercise:"飞鸟", sets:3, reps:12, weight_kg:15}
  ]
  → Write to DB → Return confirmation
```

On extraction failure, return error with format guidance.

### today_plan

Query recent training records (7 days) + user fitness preferences → LLM generates today's suggestion.

```
Input: last 7 days training records + fitness preferences
Output: suggested muscle group, exercises, sets/reps in natural language
```

Rule layer guard: if a muscle group hasn't been trained recently, prioritize it to avoid unbalanced LLM suggestions.

## Summary Agent

User sends message with chat text → LLM produces structured summary.

Input: raw chat transcript text.
Output format:

```
讨论主题：xxx
关键结论：
  - Conclusion 1
  - Conclusion 2
待办事项：
  - @person Task
决策：xxx
```

MVP: no persistence of chat messages. One request, one summary.

## Meal Agent

Input: user `meal` preferences + recent training records.

LLM generates a full-day meal plan (breakfast, lunch, dinner) with per-item nutritional estimates, informed by:

- Body data (height/weight → estimated BMR)
- Dietary preferences (calorie_target, diet_type, allergies)
- Recent training (trained → high protein, rest day → maintenance)

Output format:

```
早餐 (≈XXX kcal)
- Food 1 (Protein Xg, Carbs Xg, Fat Xg)
- Food 2
午餐 (≈XXX kcal)
- ...
晚餐 (≈XXX kcal)
- ...
```

## QA Agent

Simplest agent: user message → send to LLM with user preferences in system prompt for personalized tone → return response.

No RAG. No multi-turn history in MVP.

## Request/Response Schema

### Request: `POST /api/debug/message`

```json
{
  "user_id": "assle",
  "message": "今天练了胸 卧推80kg5组8次",
  "timestamp": "2026-05-29T16:30:00"
}
```

### Response

```json
{
  "intent": "log_training",
  "confidence": 1.0,
  "response": "已记录训练：胸 - 卧推 80kg 5组x8次",
  "data": {}
}
```

`intent` + `confidence` from Intent Router. `response` is the agent's natural language output. `data` carries structured payload (training records, meal plan, summary, etc.).

## MVP Scope

### Included
- `POST /api/debug/message` endpoint
- Intent Router with rules + LLM fallback (6 intents)
- Fitness: log_training + today_plan
- Summary: structured chat summarization
- Meal: contextual daily meal plan generation
- QA: general question answering
- SQLite persistence for training records and user preferences

### Excluded
- Real WeChat Work callback integration (debug endpoint only)
- Group bot Webhook push
- APScheduler scheduled tasks
- Multi-turn conversation history
- RAG / knowledge base
- Multi-user group chat message collection
