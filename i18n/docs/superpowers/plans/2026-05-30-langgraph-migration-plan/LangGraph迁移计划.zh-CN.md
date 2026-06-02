# LangGraph迁移实施计划

> **对于智能体工作人员：** 所需的子技能：使用 superpowers:subagent-driven-development （推荐）或 superpowers:executing-plans 来逐个任务地实施此计划。步骤使用复选框 (`- [ ]`) 语法进行跟踪。

**目标：** 将当前 MVP 迁移到 LangChain + LangGraph，同时保留 FastAPI 表面、SQLite 持久性和调试端点契约。

**架构：** 在 LLM 客户端包装器中将 `openai.AsyncOpenAI` 替换为 `langchain_openai.ChatOpenAI`。将每个代理从线性类方法转换为具有类型化状态和单一用途节点函数的 LangGraph `StateGraph`。通过`RunnableConfig`注入DB会话和LLM客户端。添加代理注册表以替换硬编码的意图→代理映射。用于多轮对话检查点的 Wire LangGraph `MemorySaver`。

**技术堆栈：** Python 3.13+、FastAPI、LangChain、LangGraph、langchain-openai、SQLAlchemy 2 异步、SQLite、Pydantic v2、pytest

---

### 任务一：添加LangChain依赖

**文件：**
- 修改：`pyproject.toml`

- [ ] **第 1 步：添加依赖项**

将 `pyproject.toml` 中的 `openai>=1.0.0` 行替换为 `langchain`、`langgraph`、`langchain-openai`。保留 `openai` 作为传递 dep。

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
    "langchain>=0.3.0",
    "langgraph>=0.4.0",
    "langchain-openai>=0.3.0",
    "apscheduler>=3.10.0",
    "python-dotenv>=1.0.0",
    "greenlet>=3.5.1",
]
```

- [ ] **第2步：安装依赖项**

运行：`uv sync`
预期：软件包安装成功，没有版本冲突。

- [ ] **第 3 步：承诺**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add langchain, langgraph, langchain-openai"
```

---

### 任务 2：用 ChatOpenAI 包装器替换 LLM 客户端

**文件：**
- 修改：`src/llm/client.py`
- 修改：`tests/test_llm.py`

- [ ] **第1步：重写`src/llm/client.py`**

```python
from langchain_openai import ChatOpenAI
from src.config import settings


class LLMClient:
    def __init__(self):
        self._model = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.7,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        response = await self._model.ainvoke(messages, temperature=temperature)
        content = response.content
        return content if content is not None else ""

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
    ) -> str:
        return await self.chat(messages, model=model, temperature=temperature)
```

- [ ] **步骤2：重写`tests/test_llm.py`**

```python
import os
from unittest.mock import AsyncMock, patch
import pytest
from langchain_core.messages import AIMessage


@pytest.mark.asyncio
async def test_llm_client_chat_returns_content():
    mock_message = AIMessage(content="Hello, I am an AI.")

    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        with patch("src.llm.client.ChatOpenAI") as mock_chat_openai_cls:
            mock_model = AsyncMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_message)
            mock_chat_openai_cls.return_value = mock_model

            from src.llm.client import LLMClient

            llm = LLMClient()
            result = await llm.chat(
                messages=[{"role": "user", "content": "Hi"}],
            )
            assert result == "Hello, I am an AI."
```

- [ ] **步骤 3：运行 LLM 测试**

运行：`DEEPSEEK_API_KEY=test uv run pytest tests/test_llm.py -v`
预期：1 次测试通过。

- [ ] **第 4 步：运行完整的测试套件以检查是否没有损坏**

运行：`DEEPSEEK_API_KEY=test uv run pytest -q`
预期：所有现有测试都通过（或确定哪些测试需要在以后的任务中更新）。

- [ ] **第 5 步：承诺**

```bash
git add src/llm/client.py tests/test_llm.py
git commit -m "refactor: replace AsyncOpenAI with langchain ChatOpenAI"
```

---

### 任务 3：将 FitnessAgent 转换为 StateGraph

**文件：**
- 创建：`src/agents/fitness/__init__.py`
- 创建：`src/agents/fitness/state.py`
- 创建：`src/agents/fitness/nodes.py`
- 创建：`src/agents/fitness/graph.py`
- 移动：`src/agents/fitness.py` → 删除（被包替换）
- 修改：`src/main.py`（更新导入路径）
- 修改：`src/router/debug.py`（更新导入路径）

- [ ] **第1步：创建`src/agents/fitness/__init__.py`**

```python
from src.agents.fitness.graph import FitnessAgent

__all__ = ["FitnessAgent"]
```

- [ ] **步骤2：创建`src/agents/fitness/state.py`**

```python
from typing import TypedDict, Optional


class FitnessState(TypedDict, total=False):
    intent: str
    message: str
    user_id: str
    raw_result: Optional[str]
    parsed_items: list[dict]
    saved_records: list[dict]
    history_text: str
    preferences: dict
    reply: str
    data: Optional[dict]
    error: Optional[str]
```

- [ ] **步骤3：创建`src/agents/fitness/nodes.py`**

```python
import json
from datetime import date
from typing import Any
from sqlalchemy import select
from langgraph.config import get_config
from src.models.training import TrainingRecord

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


def _get_llm():
    config = get_config()
    return config["configurable"]["llm"]


def _get_db():
    config = get_config()
    return config["configurable"]["db"]


async def extract_training_records(state: dict) -> dict:
    llm = _get_llm()
    try:
        raw = await llm.chat_json(
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": state["message"]},
            ],
        )
        return {"raw_result": raw}
    except Exception as e:
        return {"error": str(e), "raw_result": None}


async def validate_records(state: dict) -> dict:
    if state.get("error"):
        return {}
    raw = state.get("raw_result", "")
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return {"parsed_items": [], "error": "无法解析训练记录，请确认格式后重试。"}
    if not isinstance(items, list):
        return {"parsed_items": [], "error": "无法解析训练记录，请确认格式后重试。"}
    valid = []
    for item in items:
        required = ["muscle_group", "exercise", "sets", "reps"]
        if not all(k in item for k in required):
            continue
        valid.append(item)
    return {"parsed_items": valid}


async def persist_records(state: dict) -> dict:
    if state.get("error"):
        return {}
    db = _get_db()
    items = state.get("parsed_items", [])
    if not items:
        return {"saved_records": []}
    saved = []
    for item in items:
        try:
            record = TrainingRecord(
                user_id=state["user_id"],
                date=str(item.get("date", date.today().isoformat())),
                muscle_group=str(item["muscle_group"]),
                exercise=str(item["exercise"]),
                sets=int(item["sets"]),
                reps=int(item["reps"]),
                weight_kg=float(item["weight_kg"]) if item.get("weight_kg") is not None else None,
            )
        except (ValueError, TypeError):
            continue
        db.add(record)
        saved.append({
            "muscle_group": record.muscle_group,
            "exercise": record.exercise,
            "sets": record.sets,
            "reps": record.reps,
            "weight_kg": record.weight_kg,
        })
    await db.flush()
    return {"saved_records": saved}


async def format_log_response(state: dict) -> dict:
    saved = state.get("saved_records", [])
    if state.get("error"):
        return {"reply": state["error"]}
    if not saved:
        return {"reply": "未识别到训练记录。示例格式：打卡 今天练胸 卧推80kg5组8次"}
    return {
        "reply": f"已记录 {len(saved)} 条训练：{'、'.join(r['exercise'] for r in saved)}",
        "data": {"records": saved},
    }


async def fetch_training_history(state: dict) -> dict:
    from datetime import date, timedelta
    db = _get_db()
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    result = await db.execute(
        select(TrainingRecord)
        .where(TrainingRecord.user_id == state["user_id"])
        .where(TrainingRecord.date >= cutoff)
        .order_by(TrainingRecord.date.desc())
    )
    recent = result.scalars().all()
    history_text = "\n".join(
        f"- {r.date}: {r.muscle_group} {r.exercise} {r.sets}×{r.reps}"
        + (f" {r.weight_kg}kg" if r.weight_kg else "")
        for r in recent
    ) if recent else "暂无训练记录"
    return {"history_text": history_text}


async def fetch_user_preferences(state: dict) -> dict:
    import json
    db = _get_db()
    from src.models.preference import UserPreference, DEFAULT_PREFERENCES
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == state["user_id"])
    )
    pref = result.scalar_one_or_none()
    pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES
    return {"preferences": pref_json}


async def generate_plan(state: dict) -> dict:
    import json
    llm = _get_llm()
    try:
        prefs = state.get("preferences", {})
        reply = await llm.chat(
            messages=[
                {"role": "system", "content": PLAN_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"用户偏好：{json.dumps(prefs.get('fitness', {}), ensure_ascii=False)}\n"
                        f"最近训练：\n{state.get('history_text', '暂无训练记录')}\n"
                        f"请给出今日训练建议。"
                    ),
                },
            ],
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


async def format_plan_response(state: dict) -> dict:
    if state.get("error"):
        return {"reply": f"生成训练计划失败：{state['error']}"}
    return {"reply": state.get("reply", "无法生成训练计划。")}


def path_condition(state: dict) -> str:
    if state.get("error"):
        return "error_handler"
    intent = state.get("intent", "")
    if intent == "log_training":
        return "log_training"
    elif intent == "today_plan":
        return "today_plan"
    return "error_handler"


def log_path_condition(state: dict) -> str:
    if state.get("error"):
        return "error_handler"
    items = state.get("parsed_items")
    if items is None:
        return "error_handler"
    return "persist"


async def error_handler(state: dict) -> dict:
    return {"reply": state.get("error", "处理请求时发生错误，请稍后重试。")}
```

- [ ] **第4步：创建`src/agents/fitness/graph.py`**

```python
from langgraph.graph import StateGraph, END
from src.agents.fitness.state import FitnessState
from src.agents.fitness.nodes import (
    extract_training_records,
    validate_records,
    persist_records,
    format_log_response,
    fetch_training_history,
    fetch_user_preferences,
    generate_plan,
    format_plan_response,
    path_condition,
    log_path_condition,
    error_handler,
)
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


class FitnessAgent:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(FitnessState)

        # log_training path nodes
        builder.add_node("extract", extract_training_records)
        builder.add_node("validate", validate_records)
        builder.add_node("persist", persist_records)
        builder.add_node("format_log", format_log_response)

        # today_plan path nodes
        builder.add_node("fetch_history", fetch_training_history)
        builder.add_node("fetch_prefs", fetch_user_preferences)
        builder.add_node("generate", generate_plan)
        builder.add_node("format_plan", format_plan_response)

        # shared nodes
        builder.add_node("error_handler", error_handler)

        # entry routing
        builder.set_conditional_entry_point(
            path_condition,
            {
                "log_training": "extract",
                "today_plan": "fetch_history",
                "error_handler": "error_handler",
            },
        )

        # log_training subgraph
        builder.add_edge("extract", "validate")
        builder.add_conditional_edges(
            "validate",
            log_path_condition,
            {"persist": "persist", "error_handler": "error_handler"},
        )
        builder.add_edge("persist", "format_log")
        builder.add_edge("format_log", END)

        # today_plan subgraph
        builder.add_edge("fetch_history", "fetch_prefs")
        builder.add_edge("fetch_prefs", "generate")
        builder.add_edge("generate", "format_plan")
        builder.add_edge("format_plan", END)

        # error handler
        builder.add_edge("error_handler", END)

        return builder.compile()

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        initial_state: dict = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
        }
        config = {"configurable": {"db": db, "llm": self._llm}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
```

- [ ] **步骤 5：更新 `src/main.py` 中的导入**

改变：
```python
from src.agents.fitness import FitnessAgent
```
到：
```python
from src.agents.fitness import FitnessAgent
```
（没有变化 - 包 `__init__.py` 重新导出 `FitnessAgent`，因此导入仍然有效。）

- [ ] **步骤 6：更新 `src/router/debug.py` 中的导入**

改变：
```python
from src.agents.fitness import FitnessAgent
```
到：
```python
from src.agents.fitness import FitnessAgent
```
（相同——无需更改。）

但删除旧的 `src/agents/fitness.py` 文件：

```bash
rm src/agents/fitness.py
```

- [ ] **第 7 步：进行体能测试**

运行：`DEEPSEEK_API_KEY=test uv run pytest tests/test_fitness.py -v`
预期：两项体能测试均通过。 `mock_llm` fixture是 `AsyncMock()` - 代理的 `handle()` 方法通过图形节点调用 `self._llm.chat_json()` 和 `self._llm.chat()`，并且模拟仍然捕获这些调用。

- [ ] **第 8 步：运行完整的测试套件**

运行：`DEEPSEEK_API_KEY=test uv run pytest -q`
预期：之前通过的所有测试仍应通过。

- [ ] **第 9 步：承诺**

```bash
git rm src/agents/fitness.py
git add src/agents/fitness/__init__.py src/agents/fitness/state.py src/agents/fitness/nodes.py src/agents/fitness/graph.py
git commit -m "refactor: convert FitnessAgent to LangGraph StateGraph"
```

---

### 任务 4：将 SummaryAgent 转换为 StateGraph

**文件：**
- 创建：`src/agents/summary/__init__.py`
- 创建：`src/agents/summary/state.py`
- 创建：`src/agents/summary/nodes.py`
- 创建：`src/agents/summary/graph.py`
- 删除：`src/agents/summary.py`

- [ ] **第1步：创建`src/agents/summary/__init__.py`**

```python
from src.agents.summary.graph import SummaryAgent

__all__ = ["SummaryAgent"]
```

- [ ] **步骤2：创建`src/agents/summary/state.py`**

```python
from typing import TypedDict, Optional


class SummaryState(TypedDict, total=False):
    intent: str
    message: str
    user_id: str
    reply: str
    error: Optional[str]
```

- [ ] **步骤3：创建`src/agents/summary/nodes.py`**

```python
from langgraph.config import get_config

SUMMARY_PROMPT = """你是群聊总结助手。用以下格式总结用户提供的聊天记录：

讨论主题：<一句话概括>
关键结论：
  - <结论1>
  - <结论2>
待办事项：
  - @<负责人> <事项>
决策：<已做出的决策，无则写"无">

只返回上述格式，不要有其他说明文字。"""


async def generate_summary(state: dict) -> dict:
    config = get_config()
    llm = config["configurable"]["llm"]
    try:
        reply = await llm.chat(
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": state["message"]},
            ],
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


async def format_summary_response(state: dict) -> dict:
    if state.get("error"):
        return {"reply": f"生成总结失败：{state['error']}"}
    return {"reply": state.get("reply", "")}
```

- [ ] **第4步：创建`src/agents/summary/graph.py`**

```python
from langgraph.graph import StateGraph, END
from src.agents.summary.state import SummaryState
from src.agents.summary.nodes import generate_summary, format_summary_response
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


class SummaryAgent:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(SummaryState)
        builder.add_node("generate", generate_summary)
        builder.add_node("format", format_summary_response)
        builder.set_entry_point("generate")
        builder.add_edge("generate", "format")
        builder.add_edge("format", END)
        return builder.compile()

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        initial_state: dict = {"intent": intent, "message": message, "user_id": user_id}
        config = {"configurable": {"db": db, "llm": self._llm}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
```

- [ ] **步骤 5：删除旧文件并运行摘要测试**

```bash
rm src/agents/summary.py
DEEPSEEK_API_KEY=test uv run pytest tests/test_summary.py -v
```
预期：总结测试通过。

- [ ] **第 6 步：承诺**

```bash
git rm src/agents/summary.py
git add src/agents/summary/
git commit -m "refactor: convert SummaryAgent to LangGraph StateGraph"
```

---

### 任务 5：将 MealAgent 转换为 StateGraph

**文件：**
- 创建：`src/agents/meal/__init__.py`
- 创建：`src/agents/meal/state.py`
- 创建：`src/agents/meal/nodes.py`
- 创建：`src/agents/meal/graph.py`
- 删除：`src/agents/meal.py`

- [ ] **第1步：创建`src/agents/meal/__init__.py`**

```python
from src.agents.meal.graph import MealAgent

__all__ = ["MealAgent"]
```

- [ ] **步骤2：创建`src/agents/meal/state.py`**

```python
from typing import TypedDict, Optional


class MealState(TypedDict, total=False):
    intent: str
    message: str
    user_id: str
    preferences: dict
    trained_today: bool
    reply: str
    data: Optional[dict]
    error: Optional[str]
```

- [ ] **步骤3：创建`src/agents/meal/nodes.py`**

```python
import json
from datetime import date, timedelta
from sqlalchemy import select
from langgraph.config import get_config
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


async def fetch_preferences(state: dict) -> dict:
    db = get_config()["configurable"]["db"]
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == state["user_id"])
    )
    pref = result.scalar_one_or_none()
    pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES
    return {"preferences": pref_json}


async def check_training_today(state: dict) -> dict:
    db = get_config()["configurable"]["db"]
    cutoff = (date.today() - timedelta(days=1)).isoformat()
    result = await db.execute(
        select(TrainingRecord)
        .where(TrainingRecord.user_id == state["user_id"])
        .where(TrainingRecord.date >= cutoff)
    )
    trained = result.scalars().all()
    return {"trained_today": bool(trained)}


async def generate_meal_plan(state: dict) -> dict:
    llm = get_config()["configurable"]["llm"]
    import json
    prefs = state.get("preferences", {})
    context = (
        f"用户偏好：{json.dumps(prefs.get('meal', {}), ensure_ascii=False)}\n"
        f"身体数据：{json.dumps(prefs.get('fitness', {}).get('body', {}), ensure_ascii=False)}\n"
        f"训练目标：{prefs.get('fitness', {}).get('goal', '未设定')}\n"
        f"{'今天已训练，需要高蛋白' if state.get('trained_today') else '今天未训练，维持饮食'}"
    )
    try:
        reply = await llm.chat(
            messages=[
                {"role": "system", "content": MEAL_PROMPT},
                {"role": "user", "content": context},
            ],
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


async def format_meal_response(state: dict) -> dict:
    if state.get("error"):
        return {"reply": f"生成食谱失败：{state['error']}"}
    return {"reply": state.get("reply", "无法生成食谱。")}
```

- [ ] **第4步：创建`src/agents/meal/graph.py`**

```python
from langgraph.graph import StateGraph, END
from src.agents.meal.state import MealState
from src.agents.meal.nodes import (
    fetch_preferences,
    check_training_today,
    generate_meal_plan,
    format_meal_response,
)
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


class MealAgent:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(MealState)
        builder.add_node("fetch_prefs", fetch_preferences)
        builder.add_node("check_training", check_training_today)
        builder.add_node("generate", generate_meal_plan)
        builder.add_node("format", format_meal_response)

        builder.set_entry_point("fetch_prefs")
        builder.add_edge("fetch_prefs", "check_training")
        builder.add_edge("check_training", "generate")
        builder.add_edge("generate", "format")
        builder.add_edge("format", END)

        return builder.compile()

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        initial_state: dict = {"intent": intent, "message": message, "user_id": user_id}
        config = {"configurable": {"db": db, "llm": self._llm}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
```

- [ ] **步骤 5：删除旧文件并运行膳食测试**

```bash
rm src/agents/meal.py
DEEPSEEK_API_KEY=test uv run pytest tests/test_meal.py -v
```
预期：膳食测试通过。

- [ ] **第 6 步：承诺**

```bash
git rm src/agents/meal.py
git add src/agents/meal/
git commit -m "refactor: convert MealAgent to LangGraph StateGraph"
```

---

### 任务 6：将 QAAgent 转换为 StateGraph

**文件：**
- 创建：`src/agents/qa/__init__.py`
- 创建：`src/agents/qa/state.py`
- 创建：`src/agents/qa/nodes.py`
- 创建：`src/agents/qa/graph.py`
- 删除：`src/agents/qa.py`

- [ ] **第1步：创建`src/agents/qa/__init__.py`**

```python
from src.agents.qa.graph import QAAgent

__all__ = ["QAAgent"]
```

- [ ] **步骤2：创建`src/agents/qa/state.py`**

```python
from typing import TypedDict, Optional


class QAState(TypedDict, total=False):
    intent: str
    message: str
    user_id: str
    preferences: dict
    reply: str
    error: Optional[str]
```

- [ ] **步骤3：创建`src/agents/qa/nodes.py`**

```python
import json
from sqlalchemy import select
from langgraph.config import get_config
from src.models.preference import UserPreference, DEFAULT_PREFERENCES

QA_SYSTEM_PROMPT = """你是个人管家助手。根据用户偏好提供个性化回复。

用户偏好：
{preferences}

用友好、简洁的中文回复。"""


async def fetch_preferences(state: dict) -> dict:
    db = get_config()["configurable"]["db"]
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == state["user_id"])
    )
    pref = result.scalar_one_or_none()
    pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES
    preferences_summary = {
        "fitness": pref_json.get("fitness", {}),
        "meal": pref_json.get("meal", {}),
    }
    return {"preferences": preferences_summary}


async def generate_qa_response(state: dict) -> dict:
    llm = get_config()["configurable"]["llm"]
    import json
    try:
        reply = await llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": QA_SYSTEM_PROMPT.format(
                        preferences=json.dumps(state.get("preferences", {}), ensure_ascii=False)
                    ),
                },
                {"role": "user", "content": state["message"]},
            ],
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


async def format_qa_response(state: dict) -> dict:
    if state.get("error"):
        return {"reply": f"抱歉，暂时无法处理：{state['error']}"}
    return {"reply": state.get("reply", "")}
```

- [ ] **第4步：创建`src/agents/qa/graph.py`**

```python
from langgraph.graph import StateGraph, END
from src.agents.qa.state import QAState
from src.agents.qa.nodes import fetch_preferences, generate_qa_response, format_qa_response
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


class QAAgent:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(QAState)
        builder.add_node("fetch_prefs", fetch_preferences)
        builder.add_node("generate", generate_qa_response)
        builder.add_node("format", format_qa_response)

        builder.set_entry_point("fetch_prefs")
        builder.add_edge("fetch_prefs", "generate")
        builder.add_edge("generate", "format")
        builder.add_edge("format", END)

        return builder.compile()

    async def handle(self, intent: str, message: str, user_id: str, db) -> AgentResponse:
        initial_state: dict = {"intent": intent, "message": message, "user_id": user_id}
        config = {"configurable": {"db": db, "llm": self._llm}}
        result = await self._graph.ainvoke(initial_state, config)
        return AgentResponse(reply=result.get("reply", ""), data=result.get("data"))
```

- [ ] **步骤 5：删除旧文件并运行 QA 测试**

```bash
rm src/agents/qa.py
DEEPSEEK_API_KEY=test uv run pytest tests/test_qa.py -v
```
预期：QA 测试通过。

- [ ] **第 6 步：承诺**

```bash
git rm src/agents/qa.py
git add src/agents/qa/
git commit -m "refactor: convert QAAgent to LangGraph StateGraph"
```

---

### 任务 7：创建 BaseGraphAgent 和代理注册表

**文件：**
- 创建：`src/agents/base.py`（重写）
- 创建：`src/agents/registry.py`

- [ ] **第1步：重写`src/agents/base.py`**

```python
from abc import ABC, abstractmethod
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


class BaseGraphAgent(ABC):
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    @abstractmethod
    async def handle(
        self, intent: str, message: str, user_id: str, db
    ) -> AgentResponse:
        ...
```

- [ ] **步骤2：创建`src/agents/registry.py`**

```python
from typing import Protocol, runtime_checkable
from src.llm.client import LLMClient
from src.schemas.response import AgentResponse


@runtime_checkable
class GraphAgent(Protocol):
    async def handle(
        self, intent: str, message: str, user_id: str, db
    ) -> AgentResponse: ...


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, GraphAgent] = {}
        self._fallback: GraphAgent | None = None

    def register(self, intent: str, agent: GraphAgent):
        self._agents[intent] = agent

    def set_fallback(self, agent: GraphAgent):
        self._fallback = agent

    def get(self, intent: str) -> GraphAgent | None:
        return self._agents.get(intent, self._fallback)
```

- [ ] **第 3 步：承诺**

```bash
git add src/agents/base.py src/agents/registry.py
git commit -m "feat: add BaseGraphAgent ABC and AgentRegistry"
```

---

### 任务 8：将 AgentRegistry 连接到主设备和路由器

**文件：**
- 修改：`src/main.py`
- 修改：`src/router/debug.py`

- [ ] **第1步：更新`src/main.py`**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.config import settings
from src.llm.client import LLMClient
from src.intent.router import IntentRouter
from src.agents.fitness import FitnessAgent
from src.agents.summary import SummaryAgent
from src.agents.meal import MealAgent
from src.agents.qa import QAAgent
from src.agents.registry import AgentRegistry
from src.router.debug import create_debug_router

llm_client = LLMClient()
intent_router = IntentRouter(llm_client=llm_client)
fitness_agent = FitnessAgent(llm_client=llm_client)
summary_agent = SummaryAgent(llm_client=llm_client)
meal_agent = MealAgent(llm_client=llm_client)
qa_agent = QAAgent(llm_client=llm_client)

agent_registry = AgentRegistry()
agent_registry.register("log_training", fitness_agent)
agent_registry.register("today_plan", fitness_agent)
agent_registry.register("summarize_text", summary_agent)
agent_registry.register("make_meal_plan", meal_agent)
agent_registry.register("qa", qa_agent)
agent_registry.register("unknown", qa_agent)
agent_registry.set_fallback(qa_agent)


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
    agent_registry=agent_registry,
)
app.include_router(debug_router)
```

- [ ] **第2步：更新`src/router/debug.py`**

```python
from fastapi import APIRouter, Depends
from openai import APIError
from sqlalchemy.ext.asyncio import AsyncSession
from src.schemas.request import DebugMessageRequest
from src.schemas.response import DebugMessageResponse
from src.db.session import get_db
from src.intent.router import IntentRouter
from src.agents.registry import AgentRegistry


def create_debug_router(
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
) -> APIRouter:
    router = APIRouter(prefix="/api/debug", tags=["debug"])

    @router.post("/message")
    async def debug_message(
        req: DebugMessageRequest, db: AsyncSession = Depends(get_db)
    ) -> DebugMessageResponse:
        intent, confidence = await intent_router.route(req.message)

        agent = agent_registry.get(intent)
        try:
            result = await agent.handle(intent, req.message, req.user_id, db)
        except APIError as e:
            return DebugMessageResponse(
                intent=intent,
                confidence=confidence,
                response="LLM 服务暂时不可用，请稍后重试。",
                data={"error": str(e)},
            )

        return DebugMessageResponse(
            intent=intent,
            confidence=confidence,
            response=result.reply,
            data=result.data,
        )

    return router
```

- [ ] **第 3 步：运行完整的测试套件**

运行：`DEEPSEEK_API_KEY=test uv run pytest -q`
预期：所有测试均通过。

- [ ] **第 4 步：承诺**

```bash
git add src/main.py src/router/debug.py
git commit -m "refactor: wire AgentRegistry into main and router, remove hardcoded agent map"
```

---

### 任务 9：用于多轮对话的 Wire LangGraph MemorySaver

**文件：**
- 创建：`src/graph/__init__.py`
- 创建：`src/graph/memory.py`

- [ ] **第1步：创建`src/graph/__init__.py`**

```python
# Graph utilities package
```

- [ ] **步骤2：创建`src/graph/memory.py`**

```python
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()
```

- [ ] **步骤 3：更新代理图以使用检查点**

在每个代理的 `graph.py` 中，更新 `_build_graph()` 以接受可选的检查点：

对于 `src/agents/fitness/graph.py`，更改 `_build_graph` 中的返回：
```python
from src.graph.memory import checkpointer as _checkpointer

class FitnessAgent:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client
        self._graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(FitnessState)
        # ... node definitions unchanged ...
        return builder.compile(checkpointer=_checkpointer)
```

对其他三个代理应用相同的模式。

在 `src/agents/summary/graph.py` 中，更改：
```python
        return builder.compile()
```
到：
```python
        from src.graph.memory import checkpointer
        return builder.compile(checkpointer=checkpointer)
```

在 `src/agents/meal/graph.py` 中，进行相同的更改。

在 `src/agents/qa/graph.py` 中，进行相同的更改。

- [ ] **第4步：验证thread_id接线**

在每个代理的 `handle()` 方法中，更新配置以包含 `thread_id`：
```python
config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
```
确保设置了 `thread_id` - 这在之前是隐式的，但现在应该是显式的。更新每个代理的 `handle()` 以包含它：

```python
config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
```

- [ ] **第 5 步：运行完整的测试套件**

运行：`DEEPSEEK_API_KEY=test uv run pytest -q`
预期：所有测试均通过。

- [ ] **第 6 步：承诺**

```bash
git add src/graph/ src/agents/fitness/graph.py src/agents/summary/graph.py src/agents/meal/graph.py src/agents/qa/graph.py
git commit -m "feat: wire LangGraph MemorySaver for multi-turn conversation"
```

---

### 任务 10：最终验证

- [ ] **第 1 步：运行完整的测试套件**

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```
预期：所有测试均通过。

- [ ] **第2步：启动开发服务器并手动测试**

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

在另一个终端中：
```bash
curl -X POST http://localhost:8000/api/debug/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"assle","message":"打卡 今天练胸 卧推80kg5组8次"}'
```
预期：响应包含 `"intent":"log_training"` 和 `"response"` 以及训练日志确认。

```bash
curl -X POST http://localhost:8000/api/debug/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"assle","message":"你好"}'
```
预期：响应包含 `"intent":"qa"` 和友好回复。

- [ ] **第 3 步：如果有任何更改，请提交最终状态**

```bash
git status
```
如果干净，则无需提交。
