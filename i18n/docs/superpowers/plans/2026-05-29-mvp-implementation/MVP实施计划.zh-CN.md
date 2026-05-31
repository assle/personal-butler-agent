# Personal Butler Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MVP of the Personal Butler Agent with debug endpoint, intent routing (rules + LLM fallback), and four business agents (Fitness, Summary, Meal, QA) backed by SQLite persistence.

**Architecture:** Single-process FastAPI app. POST /api/debug/message receives user messages → IntentRouter classifies via keyword rules then LLM fallback → dispatcher calls the appropriate agent → agent uses LLM client for extraction/generation + SQLAlchemy for persistence → returns structured response.

**Tech Stack:** Python 3.13+, FastAPI, SQLAlchemy (async + aiosqlite), Pydantic, OpenAI SDK (pointed at DeepSeek), pytest + pytest-asyncio + httpx, uv.

---

## File Map

| File | Responsibility |
|------|---------------|
| `src/main.py` | FastAPI app creation, startup, route registration, agent wiring |
| `src/config.py` | Pydantic Settings loading from `.env` |
| `src/db/base.py` | SQLAlchemy `DeclarativeBase` |
| `src/db/session.py` | Async engine + session factory + `get_db` dependency |
| `src/models/training.py` | `TrainingRecord` ORM model |
| `src/models/preference.py` | `UserPreference` ORM model + default preferences helper |
| `src/schemas/request.py` | `DebugMessageRequest` Pydantic model |
| `src/schemas/response.py` | `DebugMessageResponse` + `AgentResponse` dataclass |
| `src/llm/client.py` | `LLMClient` wrapping `openai.AsyncOpenAI` pointed at DeepSeek |
| `src/intent/rules.py` | Keyword-based `IntentRule` definitions + `match_rules()` |
| `src/intent/router.py` | `IntentRouter` — rules first, LLM fallback |
| `src/agents/base.py` | `BaseAgent` ABC |
| `src/agents/fitness.py` | `FitnessAgent` — log_training + today_plan |
| `src/agents/summary.py` | `SummaryAgent` — structured chat summarization |
| `src/agents/meal.py` | `MealAgent` — contextual daily meal plan |
| `src/agents/qa.py` | `QAAgent` — general Q&A |
| `src/router/debug.py` | `POST /api/debug/message` route handler |
| `tests/conftest.py` | Shared fixtures: test DB, mock LLM client, HTTP client |
| `tests/test_intent.py` | Intent rules + router tests |
| `tests/test_fitness.py` | Fitness agent tests |
| `tests/test_summary.py` | Summary agent tests |
| `tests/test_meal.py` | Meal agent tests |
| `tests/test_qa.py` | QA agent tests |
| `tests/test_api.py` | End-to-end API integration tests |

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "personal-butler-agent"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlalchemy>=2.0.0",
    "aiosqlite>=0.20.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "openai>=1.0.0",
    "apscheduler>=3.10.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Write .env.example**

```
DEEPSEEK_API_KEY=your-api-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite+aiosqlite:///butler.db
```

- [ ] **Step 3: Write .gitignore**

```
.env
*.db
__pycache__/
*.pyc
.venv/
dist/
*.egg-info/
```

- [ ] **Step 4: Install dependencies**

Run: `uv sync`
Expected: all packages installed, uv.lock created

- [ ] **Step 5: Create directory structure**

```bash
mkdir -p src/router src/intent src/agents src/models src/schemas src/llm src/db
mkdir -p tests
touch src/__init__.py
touch src/router/__init__.py
touch src/intent/__init__.py
touch src/agents/__init__.py
touch src/models/__init__.py
touch src/schemas/__init__.py
touch src/llm/__init__.py
touch src/db/__init__.py
touch tests/__init__.py
```

- [ ] **Step 6: Init git and commit**

```bash
git init
git add -A
git commit -m "chore: scaffold project with uv, deps, directory structure"
```

---

### Task 2: Config Module

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import os
from unittest.mock import patch


def test_settings_loads_from_env():
    env_vars = {
        "DEEPSEEK_API_KEY": "sk-test-key",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "DEEPSEEK_MODEL": "deepseek-chat",
        "DATABASE_URL": "sqlite+aiosqlite:///test.db",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings()
        assert settings.deepseek_api_key == "sk-test-key"
        assert settings.deepseek_base_url == "https://api.deepseek.com"
        assert settings.deepseek_model == "deepseek-chat"
        assert settings.database_url == "sqlite+aiosqlite:///test.db"


def test_settings_use_defaults():
    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings()
        assert settings.deepseek_base_url == "https://api.deepseek.com"
        assert settings.deepseek_model == "deepseek-chat"
        assert settings.database_url == "sqlite+aiosqlite:///butler.db"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.config'`

- [ ] **Step 3: Write config module**

```python
# src/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    database_url: str = "sqlite+aiosqlite:///butler.db"


settings = Settings()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add config module with pydantic-settings"
```

---

### Task 3: Database Layer

**Files:**
- Create: `src/db/base.py`
- Create: `src/db/session.py`
- Create: `tests/conftest.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/conftest.py
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.db.base import Base


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()
```

```python
# tests/test_db.py
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_session_connects(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_base_metadata_has_tables():
    from src.db.base import Base

    table_names = Base.metadata.tables.keys()
    assert "training_records" in table_names
    assert "user_preferences" in table_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write base.py**

```python
# src/db/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 4: Write session.py**

```python
# src/db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session
```

- [ ] **Step 5: Write ORM models**

```python
# src/models/training.py
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base import Base


class TrainingRecord(Base):
    __tablename__ = "training_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(nullable=False)
    date: Mapped[str] = mapped_column(nullable=False)
    muscle_group: Mapped[str] = mapped_column(nullable=False)
    exercise: Mapped[str] = mapped_column(nullable=False)
    sets: Mapped[int] = mapped_column(nullable=False)
    reps: Mapped[int] = mapped_column(nullable=False)
    weight_kg: Mapped[Optional[float]] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now().isoformat(), nullable=False
    )
```

```python
# src/models/preference.py
from datetime import datetime
import json
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base import Base

DEFAULT_PREFERENCES = {
    "fitness": {
        "body": {"height_cm": None, "weight_kg": None, "age": None},
        "goal": "general_fitness",
        "level": "beginner",
    },
    "meal": {
        "calorie_target": None,
        "diet_type": "balanced",
        "allergies": [],
    },
}


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(nullable=False, unique=True)
    preferences: Mapped[str] = mapped_column(
        default=lambda: json.dumps(DEFAULT_PREFERENCES, ensure_ascii=False),
        nullable=False,
    )
    created_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now().isoformat(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now().isoformat(), nullable=False
    )
```

Make sure models are imported so they register on `Base.metadata`. Add to `src/models/__init__.py`:

```python
# src/models/__init__.py
from src.models.training import TrainingRecord
from src.models.preference import UserPreference

__all__ = ["TrainingRecord", "UserPreference"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: 2 PASS

- [ ] **Step 7: Commit**

```bash
git add src/db/base.py src/db/session.py src/models/training.py src/models/preference.py src/models/__init__.py tests/conftest.py tests/test_db.py
git commit -m "feat: add database layer with ORM models"
```

---

### Task 4: Pydantic Schemas

**Files:**
- Create: `src/schemas/request.py`
- Create: `src/schemas/response.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schemas.py
from datetime import datetime


def test_debug_message_request_valid():
    from src.schemas.request import DebugMessageRequest

    req = DebugMessageRequest(user_id="assle", message="hello")
    assert req.user_id == "assle"
    assert req.message == "hello"
    assert req.timestamp is None


def test_debug_message_request_with_timestamp():
    from src.schemas.request import DebugMessageRequest

    ts = "2026-05-29T16:30:00"
    req = DebugMessageRequest(user_id="assle", message="hello", timestamp=ts)
    assert req.timestamp == datetime.fromisoformat(ts)


def test_debug_message_request_empty_message_fails():
    from src.schemas.request import DebugMessageRequest
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DebugMessageRequest(user_id="assle", message="")


def test_debug_message_response_structure():
    from src.schemas.response import DebugMessageResponse

    resp = DebugMessageResponse(
        intent="qa",
        confidence=0.95,
        response="Hello!",
        data={"key": "value"},
    )
    assert resp.intent == "qa"
    assert resp.confidence == 0.95
    assert resp.response == "Hello!"
    assert resp.data == {"key": "value"}


def test_debug_message_response_data_optional():
    from src.schemas.response import DebugMessageResponse

    resp = DebugMessageResponse(
        intent="unknown",
        confidence=0.0,
        response="Sorry, I don't understand.",
    )
    assert resp.data is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write request schema**

```python
# src/schemas/request.py
from datetime import datetime
from pydantic import BaseModel, Field


class DebugMessageRequest(BaseModel):
    user_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    timestamp: datetime | None = None
```

- [ ] **Step 4: Write response schema**

```python
# src/schemas/response.py
from dataclasses import dataclass, field
from pydantic import BaseModel


@dataclass
class AgentResponse:
    reply: str
    data: dict | None = None


class DebugMessageResponse(BaseModel):
    intent: str
    confidence: float
    response: str
    data: dict | None = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_schemas.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add src/schemas/request.py src/schemas/response.py tests/test_schemas.py
git commit -m "feat: add Pydantic request and response schemas"
```

---

### Task 5: LLM Client

**Files:**
- Create: `src/llm/client.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm.py
from unittest.mock import AsyncMock, patch
import pytest
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice


@pytest.mark.asyncio
async def test_llm_client_chat_returns_content():
    mock_completion = ChatCompletion(
        id="test-id",
        model="deepseek-chat",
        created=1234567890,
        object="chat.completion",
        choices=[
            Choice(
                index=0,
                message=ChatCompletionMessage(
                    role="assistant", content="Hello, I am an AI."
                ),
                finish_reason="stop",
            )
        ],
    )

    with patch("openai.AsyncOpenAI") as mock_openai_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
        mock_openai_cls.return_value = mock_client

        from src.llm.client import LLMClient

        llm = LLMClient()
        result = await llm.chat(
            messages=[{"role": "user", "content": "Hi"}],
            model="deepseek-chat",
        )
        assert result == "Hello, I am an AI."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write LLM client**

```python
# src/llm/client.py
from openai import AsyncOpenAI
from src.config import settings


class LLMClient:
    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=model or settings.deepseek_model,
            messages=messages,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        return content if content is not None else ""

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
    ) -> str:
        """Chat with lower temperature, suitable for structured/JSON output."""
        return await self.chat(messages, model=model, temperature=temperature)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm.py -v`
Expected: 1 PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm/client.py tests/test_llm.py
git commit -m "feat: add LLM client wrapping OpenAI SDK for DeepSeek"
```

---

### Task 6: Intent Rules

**Files:**
- Create: `src/intent/rules.py`
- Create: `tests/test_intent.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_intent.py
import pytest


class TestIntentRules:
    def test_match_log_training_by_keyword(self):
        from src.intent.rules import match_rules

        assert match_rules("打卡 今天练了胸") == "log_training"
        assert match_rules("记录训练 卧推") == "log_training"

    def test_match_today_plan_by_keyword(self):
        from src.intent.rules import match_rules

        assert match_rules("今天练什么") == "today_plan"
        assert match_rules("给我训练建议") == "today_plan"

    def test_match_summarize_text_by_keyword(self):
        from src.intent.rules import match_rules

        assert match_rules("帮我总结一下这段聊天") == "summarize_text"
        assert match_rules("summary of the chat") == "summarize_text"

    def test_match_make_meal_plan_by_keyword(self):
        from src.intent.rules import match_rules

        assert match_rules("今天吃什么") == "make_meal_plan"
        assert match_rules("给我做一个meal plan") == "make_meal_plan"

    def test_no_match_returns_none(self):
        from src.intent.rules import match_rules

        assert match_rules("你好") is None
        assert match_rules("今天天气怎么样") is None
        assert match_rules("") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_intent.py -v`
Expected: 5 FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write intent rules**

```python
# src/intent/rules.py
from dataclasses import dataclass


@dataclass
class IntentRule:
    intent: str
    keywords: list[str]


RULES: list[IntentRule] = [
    IntentRule(
        "log_training",
        ["打卡", "记录训练", "练了", "训练"],
    ),
    IntentRule(
        "today_plan",
        ["今天练什么", "今日计划", "训练建议"],
    ),
    IntentRule(
        "summarize_text",
        ["总结", "summary", "帮我总结"],
    ),
    IntentRule(
        "make_meal_plan",
        ["食谱", "吃什么", "meal plan", "饮食"],
    ),
]


def match_rules(message: str) -> str | None:
    if not message or not message.strip():
        return None
    message_lower = message.lower()
    for rule in RULES:
        for keyword in rule.keywords:
            if keyword.lower() in message_lower:
                return rule.intent
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_intent.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/intent/rules.py tests/test_intent.py
git commit -m "feat: add intent rule matching with keywords"
```

---

### Task 7: Intent Router

**Files:**
- Create: `src/intent/router.py`
- Append to: `tests/test_intent.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intent.py`:

```python
from unittest.mock import AsyncMock, patch


class TestIntentRouter:
    @pytest.mark.asyncio
    async def test_rule_match_skips_llm(self):
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("打卡 今天练了胸")
        assert intent == "log_training"
        assert confidence == 1.0
        mock_llm.chat_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_fallback_when_no_rule_match(self):
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        mock_llm.chat_json.return_value = '{"intent": "qa", "confidence": 0.85}'
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("今天天气怎么样")
        assert intent == "qa"
        assert confidence == 0.85
        mock_llm.chat_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_unknown_intent_falls_back_to_unknown(self):
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        mock_llm.chat_json.return_value = '{"intent": "some_fake_intent", "confidence": 0.5}'
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("blah blah")
        assert intent == "unknown"
        assert confidence == 0.5

    @pytest.mark.asyncio
    async def test_empty_message_returns_unknown(self):
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("")
        assert intent == "unknown"
        assert confidence == 1.0
        mock_llm.chat_json.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_intent.py::TestIntentRouter -v`
Expected: 4 FAIL — `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Write intent router**

```python
# src/intent/router.py
import json

from src.intent.rules import match_rules
from src.llm.client import LLMClient

KNOWN_INTENTS = {
    "log_training",
    "today_plan",
    "summarize_text",
    "make_meal_plan",
    "qa",
    "unknown",
}

SYSTEM_PROMPT = """你是一个意图分类器。分析用户消息，返回以下意图之一：

- log_training: 用户想记录训练数据（打卡、记录训练内容）
- today_plan: 用户想获取今日训练计划建议
- summarize_text: 用户想总结一段文本/聊天记录
- make_meal_plan: 用户想要食谱/饮食计划
- qa: 一般性问题或对话
- unknown: 无法识别的消息

只返回 JSON，不要有其他文字：
{"intent": "<intent>", "confidence": <0.0-1.0>}"""


class IntentRouter:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def route(self, message: str) -> tuple[str, float]:
        if not message or not message.strip():
            return ("unknown", 1.0)

        rule_match = match_rules(message)
        if rule_match is not None:
            return (rule_match, 1.0)

        return await self._llm_classify(message)

    async def _llm_classify(self, message: str) -> tuple[str, float]:
        try:
            raw = await self._llm.chat_json(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
            )
            result = json.loads(raw)
            intent = result.get("intent", "unknown")
            if intent not in KNOWN_INTENTS:
                intent = "unknown"
            confidence = float(result.get("confidence", 0.0))
            return (intent, confidence)
        except (json.JSONDecodeError, KeyError, ValueError):
            return ("unknown", 0.0)
```

- [ ] **Step 4: Run all intent tests to verify they pass**

Run: `uv run pytest tests/test_intent.py -v`
Expected: 9 PASS (5 rules + 4 router)

- [ ] **Step 5: Commit**

```bash
git add src/intent/router.py tests/test_intent.py
git commit -m "feat: add intent router with rule-first LLM-fallback"
```

---

### Task 8: Agent Base Class

**Files:**
- Create: `src/agents/base.py`

- [ ] **Step 1: Write base class**

```python
# src/agents/base.py
from abc import ABC, abstractmethod
from sqlalchemy.ext.asyncio import AsyncSession
from src.schemas.response import AgentResponse
from src.llm.client import LLMClient


class BaseAgent(ABC):
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    @abstractmethod
    async def handle(
        self, intent: str, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        ...
```

- [ ] **Step 2: Commit**

```bash
git add src/agents/base.py
git commit -m "feat: add BaseAgent abstract class"
```

---

### Task 9: Fitness Agent

**Files:**
- Create: `src/agents/fitness.py`
- Create: `tests/test_fitness.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fitness.py
import json
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from src.models.training import TrainingRecord
from src.models.preference import UserPreference, DEFAULT_PREFERENCES


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def fitness_agent(mock_llm):
    from src.agents.fitness import FitnessAgent

    return FitnessAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_log_training_extracts_and_saves(db_session, fitness_agent, mock_llm):
    records_json = json.dumps([
        {
            "date": "2026-05-29",
            "muscle_group": "胸",
            "exercise": "卧推",
            "sets": 5,
            "reps": 8,
            "weight_kg": 80.0,
        },
        {
            "date": "2026-05-29",
            "muscle_group": "胸",
            "exercise": "飞鸟",
            "sets": 3,
            "reps": 12,
            "weight_kg": 15.0,
        },
    ])
    mock_llm.chat_json.return_value = records_json

    result = await fitness_agent.handle(
        intent="log_training",
        message="打卡 今天练胸 卧推80kg5组8次 飞鸟15kg3组12次",
        user_id="assle",
        db=db_session,
    )

    assert "已记录" in result.reply
    assert len(result.data["records"]) == 2

    stmt = select(TrainingRecord).where(TrainingRecord.user_id == "assle")
    db_result = await db_session.execute(stmt)
    records = db_result.scalars().all()
    assert len(records) == 2
    assert records[0].muscle_group == "胸"
    assert records[0].exercise == "卧推"
    assert records[0].weight_kg == 80.0


@pytest.mark.asyncio
async def test_today_plan_queries_history_and_generates(db_session, fitness_agent, mock_llm):
    from datetime import date, timedelta

    records = [
        TrainingRecord(
            user_id="assle",
            date=(date.today() - timedelta(days=i)).isoformat(),
            muscle_group=mg,
            exercise=ex,
            sets=3,
            reps=10,
            weight_kg=60.0,
        )
        for i, (mg, ex) in enumerate([
            ("胸", "卧推"), ("背", "引体向上"), ("腿", "深蹲"),
        ])
    ]
    for r in records:
        db_session.add(r)
    await db_session.flush()

    pref = UserPreference(
        user_id="assle",
        preferences=json.dumps(DEFAULT_PREFERENCES, ensure_ascii=False),
    )
    db_session.add(pref)
    await db_session.flush()

    mock_llm.chat.return_value = "今天建议练肩部，推荐动作：哑铃推举..."

    result = await fitness_agent.handle(
        intent="today_plan",
        message="今天练什么",
        user_id="assle",
        db=db_session,
    )

    assert "肩" in result.reply or "哑铃" in result.reply
    mock_llm.chat.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fitness.py -v`
Expected: 2 FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write fitness agent**

```python
# src/agents/fitness.py
import json
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.schemas.response import AgentResponse
from src.models.training import TrainingRecord
from src.models.preference import UserPreference, DEFAULT_PREFERENCES

EXTRACTION_PROMPT = """从用户消息中提取训练记录。返回 JSON 数组，每条记录包含：
- date: 训练日期 YYYY-MM-DD（未指定则用今天）
- muscle_group: 训练部位（胸/背/腿/肩/臂/核心）
- exercise: 动作名称
- sets: 组数（整数）
- reps: 次数（整数）
- weight_kg: 重量kg（自重训练可为null）

如果无法提取任何记录，返回空数组 []。
只返回 JSON，不要有其他文字。"""

PLAN_PROMPT = """你是健身教练。根据用户最近的训练记录和偏好，生成今日训练建议。
考虑：部位轮换（避免连续练同一部位）、用户目标和水平。
用自然语言给出建议部位、推荐动作、组数次数。"""


class FitnessAgent(BaseAgent):
    async def handle(
        self, intent: str, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        if intent == "log_training":
            return await self._log_training(message, user_id, db)
        elif intent == "today_plan":
            return await self._today_plan(message, user_id, db)
        return AgentResponse(reply="Unknown fitness intent")

    async def _log_training(
        self, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        raw = await self._llm.chat_json(
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": message},
            ],
        )
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            return AgentResponse(reply="无法解析训练记录，请确认格式后重试。")

        if not items:
            return AgentResponse(reply="未识别到训练记录。示例格式：打卡 今天练胸 卧推80kg5组8次")

        saved = []
        for item in items:
            record = TrainingRecord(
                user_id=user_id,
                date=item.get("date", date.today().isoformat()),
                muscle_group=item["muscle_group"],
                exercise=item["exercise"],
                sets=item["sets"],
                reps=item["reps"],
                weight_kg=item.get("weight_kg"),
            )
            db.add(record)
            saved.append(
                {
                    "muscle_group": record.muscle_group,
                    "exercise": record.exercise,
                    "sets": record.sets,
                    "reps": record.reps,
                    "weight_kg": record.weight_kg,
                }
            )

        await db.flush()
        return AgentResponse(
            reply=f"已记录 {len(saved)} 条训练：{'、'.join(r['exercise'] for r in saved)}",
            data={"records": saved},
        )

    async def _today_plan(
        self, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        result = await db.execute(
            select(TrainingRecord)
            .where(TrainingRecord.user_id == user_id)
            .where(TrainingRecord.date >= cutoff)
            .order_by(TrainingRecord.date.desc())
        )
        recent = result.scalars().all()

        result = await db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        pref = result.scalar_one_or_none()
        pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES

        history_text = "\n".join(
            f"- {r.date}: {r.muscle_group} {r.exercise} {r.sets}×{r.reps}"
            + (f" {r.weight_kg}kg" if r.weight_kg else "")
            for r in recent
        ) if recent else "暂无训练记录"

        reply = await self._llm.chat(
            messages=[
                {"role": "system", "content": PLAN_PROMPT},
                {
                    "role": "user",
                    "content": f"用户偏好：{json.dumps(pref_json['fitness'], ensure_ascii=False)}\n最近训练：\n{history_text}\n请给出今日训练建议。",
                },
            ],
        )
        return AgentResponse(reply=reply)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fitness.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/fitness.py tests/test_fitness.py
git commit -m "feat: add fitness agent with log_training and today_plan"
```

---

### Task 10: Summary Agent

**Files:**
- Create: `src/agents/summary.py`
- Create: `tests/test_summary.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_summary.py
from unittest.mock import AsyncMock
import pytest


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def summary_agent(mock_llm):
    from src.agents.summary import SummaryAgent

    return SummaryAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_summarize_returns_structured_output(db_session, summary_agent, mock_llm):
    mock_llm.chat.return_value = (
        "讨论主题：项目排期\n"
        "关键结论：\n"
        "  - 周五前完成前端\n"
        "  - 下周一联调\n"
        "待办事项：\n"
        "  - @张三 提交接口文档\n"
        "决策：使用 FastAPI 作为后端框架"
    )

    result = await summary_agent.handle(
        intent="summarize_text",
        message="这是我们要总结的群聊文本内容...",
        user_id="assle",
        db=db_session,
    )

    assert "讨论主题" in result.reply
    assert "关键结论" in result.reply
    assert "待办事项" in result.reply
    assert "决策" in result.reply
    mock_llm.chat.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_summary.py -v`
Expected: 1 FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write summary agent**

```python
# src/agents/summary.py
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.schemas.response import AgentResponse

SUMMARY_PROMPT = """你是群聊总结助手。用以下格式总结用户提供的聊天记录：

讨论主题：<一句话概括>
关键结论：
  - <结论1>
  - <结论2>
待办事项：
  - @<负责人> <事项>
决策：<已做出的决策，无则写"无">

只返回上述格式，不要有其他说明文字。"""


class SummaryAgent(BaseAgent):
    async def handle(
        self, intent: str, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        reply = await self._llm.chat(
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": message},
            ],
        )
        return AgentResponse(reply=reply)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_summary.py -v`
Expected: 1 PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/summary.py tests/test_summary.py
git commit -m "feat: add summary agent with structured output"
```

---

### Task 11: Meal Agent

**Files:**
- Create: `src/agents/meal.py`
- Create: `tests/test_meal.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_meal.py
import json
from unittest.mock import AsyncMock
import pytest
from src.models.preference import UserPreference, DEFAULT_PREFERENCES


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def meal_agent(mock_llm):
    from src.agents.meal import MealAgent

    return MealAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_meal_plan_includes_nutrition(db_session, meal_agent, mock_llm):
    pref = UserPreference(
        user_id="assle",
        preferences=json.dumps(DEFAULT_PREFERENCES, ensure_ascii=False),
    )
    db_session.add(pref)
    await db_session.flush()

    mock_llm.chat.return_value = (
        "早餐 (≈450 kcal)\n"
        "- 燕麦粥 (蛋白质12g, 碳水60g, 脂肪8g)\n"
        "- 煮鸡蛋×2 (蛋白质12g, 碳水1g, 脂肪10g)\n"
        "午餐 (≈700 kcal)\n"
        "- 鸡胸肉 (蛋白质40g, 碳水0g, 脂肪5g)\n"
        "- 糙米饭 (蛋白质5g, 碳水50g, 脂肪2g)\n"
        "晚餐 (≈550 kcal)\n"
        "- 三文鱼 (蛋白质35g, 碳水0g, 脂肪15g)\n"
        "- 炒蔬菜 (蛋白质3g, 碳水15g, 脂肪5g)"
    )

    result = await meal_agent.handle(
        intent="make_meal_plan",
        message="今天吃什么",
        user_id="assle",
        db=db_session,
    )

    assert "早餐" in result.reply
    assert "蛋白质" in result.reply
    assert "kcal" in result.reply
    mock_llm.chat.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_meal.py -v`
Expected: 1 FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write meal agent**

```python
# src/agents/meal.py
import json
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.schemas.response import AgentResponse
from src.models.preference import UserPreference, DEFAULT_PREFERENCES
from src.models.training import TrainingRecord

MEAL_PROMPT = """你是营养师。根据用户信息和最近训练情况，生成一日三餐食谱。

要求：
- 每餐给出具体食物和营养素估算（蛋白质、碳水、脂肪、卡路里）
- 考虑用户热量目标、饮食类型、过敏原
- 有训练日提高蛋白质比例
- 用中文输出，格式如下：

早餐 (≈XXX kcal)
- 食物名 (蛋白质Xg, 碳水Xg, 脂肪Xg)
午餐 (≈XXX kcal)
- ...
晚餐 (≈XXX kcal)
- ..."""


class MealAgent(BaseAgent):
    async def handle(
        self, intent: str, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        result = await db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        pref = result.scalar_one_or_none()
        pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES

        cutoff = (date.today() - timedelta(days=1)).isoformat()
        result = await db.execute(
            select(TrainingRecord)
            .where(TrainingRecord.user_id == user_id)
            .where(TrainingRecord.date >= cutoff)
        )
        trained_today = result.scalars().all()

        context = (
            f"用户偏好：{json.dumps(pref_json['meal'], ensure_ascii=False)}\n"
            f"身体数据：{json.dumps(pref_json['fitness']['body'], ensure_ascii=False)}\n"
            f"训练目标：{pref_json['fitness']['goal']}\n"
            f"{'今天已训练，需要高蛋白' if trained_today else '今天未训练，维持饮食'}"
        )

        reply = await self._llm.chat(
            messages=[
                {"role": "system", "content": MEAL_PROMPT},
                {"role": "user", "content": context},
            ],
        )
        return AgentResponse(reply=reply)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_meal.py -v`
Expected: 1 PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/meal.py tests/test_meal.py
git commit -m "feat: add meal agent with nutritional breakdown"
```

---

### Task 12: QA Agent

**Files:**
- Create: `src/agents/qa.py`
- Create: `tests/test_qa.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qa.py
import json
from unittest.mock import AsyncMock
import pytest
from src.models.preference import UserPreference, DEFAULT_PREFERENCES


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def qa_agent(mock_llm):
    from src.agents.qa import QAAgent

    return QAAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_qa_responds_with_user_context(db_session, qa_agent, mock_llm):
    pref = UserPreference(
        user_id="assle",
        preferences=json.dumps(DEFAULT_PREFERENCES, ensure_ascii=False),
    )
    db_session.add(pref)
    await db_session.flush()

    mock_llm.chat.return_value = "你好！有什么可以帮你的？"

    result = await qa_agent.handle(
        intent="qa",
        message="你好",
        user_id="assle",
        db=db_session,
    )

    assert "你好" in result.reply
    mock_llm.chat.assert_called_once()

    call_messages = mock_llm.chat.call_args[1]["messages"]
    system_msg = call_messages[0]["content"]
    assert "健身" in system_msg or "饮食" in system_msg


@pytest.mark.asyncio
async def test_qa_without_preferences_works(db_session, qa_agent, mock_llm):
    mock_llm.chat.return_value = "有什么可以帮你的？"

    result = await qa_agent.handle(
        intent="qa",
        message="你好",
        user_id="new_user",
        db=db_session,
    )

    assert len(result.reply) > 0
    mock_llm.chat.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_qa.py -v`
Expected: 2 FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write QA agent**

```python
# src/agents/qa.py
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.schemas.response import AgentResponse
from src.models.preference import UserPreference, DEFAULT_PREFERENCES

QA_SYSTEM_PROMPT = """你是个人管家助手。根据用户偏好提供个性化回复。

用户偏好：
{preferences}

用友好、简洁的中文回复。"""


class QAAgent(BaseAgent):
    async def handle(
        self, intent: str, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        result = await db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        pref = result.scalar_one_or_none()
        pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES

        preferences_summary = {
            "fitness": pref_json.get("fitness", {}),
            "meal": pref_json.get("meal", {}),
        }

        reply = await self._llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": QA_SYSTEM_PROMPT.format(
                        preferences=json.dumps(preferences_summary, ensure_ascii=False)
                    ),
                },
                {"role": "user", "content": message},
            ],
        )
        return AgentResponse(reply=reply)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_qa.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/agents/qa.py tests/test_qa.py
git commit -m "feat: add QA agent with preference-aware responses"
```

---

### Task 13: Debug Router + Main App

**Files:**
- Create: `src/router/debug.py`
- Create: `src/main.py`
- Modify: `tests/conftest.py` (add HTTP client fixture)
- Create: `tests/test_api.py`

- [ ] **Step 1: Add HTTP client fixture to conftest**

Append to `tests/conftest.py`:

```python
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture
async def http_client():
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
```

- [ ] **Step 2: Write the failing API test**

```python
# tests/test_api.py
import json
from unittest.mock import AsyncMock, patch
import pytest
from src.models.preference import UserPreference, DEFAULT_PREFERENCES


@pytest.mark.asyncio
async def test_debug_endpoint_log_training(http_client, db_session):
    mock_llm_instance = AsyncMock()
    mock_llm_instance.chat_json.return_value = json.dumps([
        {
            "date": "2026-05-29",
            "muscle_group": "胸",
            "exercise": "卧推",
            "sets": 5,
            "reps": 8,
            "weight_kg": 80.0,
        }
    ])

    with patch("src.main.llm_client", mock_llm_instance):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "打卡 今天练胸 卧推80kg5组8次",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "log_training"
    assert body["confidence"] == 1.0
    assert "卧推" in body["response"]


@pytest.mark.asyncio
async def test_debug_endpoint_qa(http_client, db_session):
    mock_llm_instance = AsyncMock()
    mock_llm_instance.chat.return_value = "你好！有什么可以帮你的？"

    with patch("src.main.llm_client", mock_llm_instance):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "你好",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "qa"
    assert body["confidence"] == 1.0
    assert len(body["response"]) > 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py -v`
Expected: 2 FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Write debug router**

```python
# src/router/debug.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.schemas.request import DebugMessageRequest
from src.schemas.response import DebugMessageResponse
from src.db.session import get_db
from src.intent.router import IntentRouter
from src.agents.fitness import FitnessAgent
from src.agents.summary import SummaryAgent
from src.agents.meal import MealAgent
from src.agents.qa import QAAgent

router = APIRouter(prefix="/api/debug", tags=["debug"])


def create_debug_router(
    intent_router: IntentRouter,
    fitness_agent: FitnessAgent,
    summary_agent: SummaryAgent,
    meal_agent: MealAgent,
    qa_agent: QAAgent,
) -> APIRouter:
    @router.post("/message")
    async def debug_message(
        req: DebugMessageRequest, db: AsyncSession = Depends(get_db)
    ) -> DebugMessageResponse:
        intent, confidence = await intent_router.route(req.message)

        agent_map = {
            "log_training": fitness_agent,
            "today_plan": fitness_agent,
            "summarize_text": summary_agent,
            "make_meal_plan": meal_agent,
            "qa": qa_agent,
            "unknown": qa_agent,
        }

        agent = agent_map.get(intent, qa_agent)
        result = await agent.handle(intent, req.message, req.user_id, db)

        return DebugMessageResponse(
            intent=intent,
            confidence=confidence,
            response=result.reply,
            data=result.data,
        )

    return router
```

- [ ] **Step 5: Write main app**

```python
# src/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.config import settings
from src.llm.client import LLMClient
from src.intent.router import IntentRouter
from src.agents.fitness import FitnessAgent
from src.agents.summary import SummaryAgent
from src.agents.meal import MealAgent
from src.agents.qa import QAAgent
from src.router.debug import create_debug_router

llm_client = LLMClient()
intent_router = IntentRouter(llm_client=llm_client)
fitness_agent = FitnessAgent(llm_client=llm_client)
summary_agent = SummaryAgent(llm_client=llm_client)
meal_agent = MealAgent(llm_client=llm_client)
qa_agent = QAAgent(llm_client=llm_client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.db.base import Base
    from src.db.session import engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Personal Butler Agent", version="0.1.0", lifespan=lifespan)

debug_router = create_debug_router(
    intent_router=intent_router,
    fitness_agent=fitness_agent,
    summary_agent=summary_agent,
    meal_agent=meal_agent,
    qa_agent=qa_agent,
)
app.include_router(debug_router)
```

- [ ] **Step 6: Run API tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: 2 PASS

- [ ] **Step 7: Run all tests to verify nothing is broken**

Run: `uv run pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/router/debug.py src/main.py tests/conftest.py tests/test_api.py
git commit -m "feat: add debug endpoint and main app wiring"
```

---

### Task 14: End-to-End Smoke Test

**Files:**
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write smoke test**

```python
# tests/test_smoke.py
import json
from unittest.mock import AsyncMock, patch
import pytest
from src.models.preference import UserPreference, DEFAULT_PREFERENCES


@pytest.mark.asyncio
async def test_full_flow_log_training_to_plan(http_client, db_session):
    """Full flow: log training, then ask for today's plan."""
    mock_llm = AsyncMock()
    mock_llm.chat_json.return_value = json.dumps([
        {
            "date": "2026-05-29",
            "muscle_group": "腿",
            "exercise": "深蹲",
            "sets": 5,
            "reps": 5,
            "weight_kg": 100.0,
        }
    ])
    mock_llm.chat.return_value = "根据你最近的训练，建议今天练胸：平板卧推 4×8..."

    with patch("src.main.llm_client", mock_llm):
        # Step 1: log training
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "打卡 深蹲100kg5组5次",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["intent"] == "log_training"
        assert body["data"]["records"][0]["exercise"] == "深蹲"

        # Reset mock for next call
        mock_llm.chat_json.reset_mock()
        mock_llm.chat_json.return_value = json.dumps([
            {
                "date": "2026-05-29",
                "muscle_group": "胸",
                "exercise": "卧推",
                "sets": 4,
                "reps": 8,
                "weight_kg": 80.0,
            }
        ])

        # Step 2: ask for plan
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "今天练什么",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["intent"] == "today_plan"
        assert len(body["response"]) > 0


@pytest.mark.asyncio
async def test_full_flow_meal_and_summary(http_client, db_session):
    """Full flow: meal plan, then summarize."""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = (
        "讨论主题：版本发布\n关键结论：\n  - 周五发版\n待办事项：\n  - 无\n决策：正常发布"
    )

    with patch("src.main.llm_client", mock_llm):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "帮我总结：张三说周五发版，李四同意了。",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["intent"] == "summarize_text"
```

- [ ] **Step 2: Run smoke tests**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: 2 PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: add end-to-end smoke tests"
```

---

### Task 15: Verify App Starts

- [ ] **Step 1: Start the dev server**

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Expected: server starts without errors, logs show "Uvicorn running on http://0.0.0.0:8000"

- [ ] **Step 2: Test with curl (in another terminal)**

```bash
curl -X POST http://localhost:8000/api/debug/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"assle","message":"你好"}'
```

Expected: JSON response with `intent`, `confidence`, `response` fields, status 200

- [ ] **Step 3: Commit (if any adjustments needed)**

```bash
git add -A
git commit -m "chore: final adjustments after manual verification"
```
