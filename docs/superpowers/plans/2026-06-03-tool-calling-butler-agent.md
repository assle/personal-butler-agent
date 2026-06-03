# Tool-Calling Butler Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the main private-chat and trigger-message execution path with a LangGraph tool-calling ButlerAgent while preserving deterministic group-message collection and all existing public API contracts.

**Architecture:** Add a new `src/agents/butler/` package that wraps existing domain agents and services as LangChain tools, then runs an LLM bound to those tools through a LangGraph `ToolNode` loop. Keep existing Fitness, Meal, Summary, QA, IntentRouter, and AgentRegistry modules available, but wire debug and WeChat reply paths to ButlerAgent for messages that should receive a response. Add a lightweight web search service behind configuration so `search_web` can degrade cleanly when disabled.

**Tech Stack:** Python 3.13+, FastAPI, LangChain Core tools/messages, LangGraph `StateGraph` + `ToolNode`, langchain-openai `ChatOpenAI.bind_tools`, httpx, Pydantic Settings, pytest + pytest-asyncio.

---

## File Structure

- Modify `src/llm/client.py`: keep `chat()` and `chat_json()` compatible; add tool-binding/message invocation support for ButlerAgent.
- Modify `tests/test_llm.py`: cover new LLMClient tool-calling methods without a real LLM call.
- Modify `src/config.py`: add `web_search_*` settings.
- Modify `tests/test_config.py`: cover search settings from env and defaults.
- Modify `.env.example`: document disabled-by-default web search settings.
- Create `src/search/__init__.py`: export search service and result schema.
- Create `src/search/schemas.py`: dataclass for normalized search results.
- Create `src/search/service.py`: async Tavily-backed search service with disabled and failure fallbacks.
- Create `tests/test_web_search_service.py`: cover disabled, success, and HTTP failure behavior.
- Create `src/agents/butler/__init__.py`: export ButlerAgent.
- Create `src/agents/butler/state.py`: LangGraph state with `messages` reducer.
- Create `src/agents/butler/prompts.py`: total-control system prompt.
- Create `src/agents/butler/tools.py`: tool factory and tool context wrapper around existing agents/services.
- Create `src/agents/butler/nodes.py`: agent node, final reply extraction, error node.
- Create `src/agents/butler/graph.py`: ButlerAgent graph assembly and `handle()` method.
- Create `tests/test_butler_tools.py`: cover domain tool wrappers and knowledge/search tool results.
- Create `tests/test_butler_agent.py`: cover tool-calling graph loop with fake LLM responses.
- Modify `src/main.py`: instantiate ButlerAgent and inject it into routes.
- Modify `src/router/debug.py`: route private and group-trigger replies to ButlerAgent while preserving group collection.
- Modify `tests/test_api.py`: update debug API expectations for `intent="butler"` and group protection behavior.
- Modify `src/wechat/callback_handler.py`: use ButlerAgent for replyable text/voice messages.
- Modify `src/wechat/callback_router.py`: pass ButlerAgent through background processing.
- Modify `src/wechat/message_handler.py`: update legacy WebSocket handler for consistency.
- Modify `tests/test_aibot_callback.py`: cover callback path calling ButlerAgent and preserving non-trigger group silence.
- Modify `docs/agent/active-context.md`: record new main execution path.
- Modify `docs/agent/patterns.md`: add ButlerAgent/tool wrapper pattern.
- Modify `docs/agent/decisions.md`: add ADR for tool-calling main entry.
- Modify `docs/agent/config-variables.md`: document web search config.
- Modify `docs/agent/troubleshooting.md`: add tool-calling and web-search checks.
- Modify `CLAUDE.md` and `AGENTS.md` only if their main-flow description changes; keep them byte-for-byte identical.

---

### Task 1: Add LLMClient Tool-Calling Support

**Files:**
- Modify: `src/llm/client.py`
- Modify: `tests/test_llm.py`

- [ ] **Step 1: Write failing tests for message invocation and tool binding**

Append these tests to `tests/test_llm.py`:

```python
@pytest.mark.asyncio
async def test_llm_client_ainvoke_messages_returns_message_object():
    """验证 LLMClient.ainvoke_messages() 返回原始 LangChain 消息对象

    返回:
        None；通过断言确认工具调用场景可以保留 AIMessage 元数据
    """
    mock_message = AIMessage(content="final answer")

    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        with patch("src.llm.client.ChatOpenAI") as mock_chat_openai_cls:
            mock_model = AsyncMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_message)
            mock_chat_openai_cls.return_value = mock_model

            from src.llm.client import LLMClient

            llm = LLMClient()
            result = await llm.ainvoke_messages(
                messages=[{"role": "user", "content": "Hi"}],
            )

            assert result is mock_message
            mock_model.ainvoke.assert_awaited_once()


def test_llm_client_bind_tools_delegates_to_chat_model():
    """验证 LLMClient.bind_tools() 透传到底层 ChatOpenAI 实例

    返回:
        None；通过断言确认 ButlerAgent 可以获取绑定工具后的 runnable
    """
    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        with patch("src.llm.client.ChatOpenAI") as mock_chat_openai_cls:
            mock_model = AsyncMock()
            bound_model = object()
            mock_model.bind_tools.return_value = bound_model
            mock_chat_openai_cls.return_value = mock_model

            from src.llm.client import LLMClient

            llm = LLMClient()
            tools = [lambda query: query]
            result = llm.bind_tools(tools)

            assert result is bound_model
            mock_model.bind_tools.assert_called_once_with(tools)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_llm.py -q
```

Expected: the new tests fail with `AttributeError: 'LLMClient' object has no attribute 'ainvoke_messages'` or `bind_tools`.

- [ ] **Step 3: Implement minimal LLMClient methods**

Update `src/llm/client.py`:

```python
"""
LLM 客户端封装
基于 LangChain ChatOpenAI 封装 DeepSeek API 调用，提供普通聊天、JSON 输出和 tool-calling 消息调用

在总流程中的位置:
  main.py 创建 LLMClient 单例 → 注入到 IntentRouter、各领域 agent 和 ButlerAgent
  IntentRouter: chat_json 用于意图分类
  各领域 agent: chat 用于自然语言生成，chat_json 用于结构化数据提取
  ButlerAgent: bind_tools/ainvoke_messages 用于保留 AIMessage.tool_calls 并驱动 ToolNode

Workflow:
  所有 LLM 调用经过此客户端，统一管理 base_url、api_key、temperature 和工具绑定入口
"""
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from src.config import settings


class LLMClient:
    """LLM 客户端，封装 DeepSeek API 的调用细节"""

    def __init__(self):
        """初始化 LLM 客户端，根据配置创建 ChatOpenAI 实例

        从 settings 读取 deepseek_model、api_key、base_url 等参数
        """
        self._model = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.7,
        )

    def bind_tools(self, tools: list[Any]) -> Runnable:
        """绑定 LangChain 工具并返回可调用 runnable

        参数:
            tools: LangChain tool、BaseTool 或兼容 callable 列表

        返回:
            Runnable: 已绑定工具的聊天模型 runnable
        """
        return self._model.bind_tools(tools)

    async def ainvoke_messages(
        self,
        messages: list[dict[str, str]] | list[BaseMessage],
        *,
        tools: list[Any] | None = None,
        temperature: float = 0.7,
    ) -> BaseMessage:
        """发送消息并返回原始 LangChain 消息对象

        参数:
            messages: 消息列表，支持 dict 或 BaseMessage
            tools: 可选工具列表；提供时先绑定工具再调用
            temperature: 生成温度

        返回:
            BaseMessage: LLM 返回的原始消息，保留 tool_calls 等元数据
        """
        model = self.bind_tools(tools) if tools else self._model
        return await model.ainvoke(messages, temperature=temperature)

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        """发送聊天消息，返回自然语言回复

        参数:
            messages: 消息列表，每条为 {"role": "system"|"user"|"assistant", "content": ...}
            model: 模型名称，默认使用 settings 中配置的模型
            temperature: 生成温度，0-1 之间，越高越随机

        返回:
            str: LLM 返回的自然语言文本，保证不为 None
        """
        response = await self.ainvoke_messages(messages, temperature=temperature)
        content = response.content
        return content if content is not None else ""

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.3,
    ) -> str:
        """发送聊天消息，返回 JSON 格式回复（使用更低温度提高一致性）

        与 chat 方法相同，但默认 temperature 更低，适用于结构化数据提取场景

        参数:
            messages: 消息列表
            model: 模型名称
            temperature: 生成温度，默认 0.3

        返回:
            str: LLM 返回的文本内容
        """
        return await self.chat(messages, model=model, temperature=temperature)
```

- [ ] **Step 4: Run LLM tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_llm.py -q
```

Expected: all tests in `tests/test_llm.py` pass.

- [ ] **Step 5: Commit**

```bash
git add src/llm/client.py tests/test_llm.py
git commit -m "feat: add tool-calling llm client methods"
```

---

### Task 2: Add Web Search Configuration And Service

**Files:**
- Modify: `src/config.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`
- Create: `src/search/__init__.py`
- Create: `src/search/schemas.py`
- Create: `src/search/service.py`
- Create: `tests/test_web_search_service.py`

- [ ] **Step 1: Write failing config tests**

Append to `tests/test_config.py`:

```python
def test_settings_loads_web_search_env():
    """验证 Settings 可以从环境变量读取联网搜索配置

    返回:
        None；通过断言确认搜索配置字段完成绑定
    """
    env_vars = {
        "DEEPSEEK_API_KEY": "sk-test-key",
        "WEB_SEARCH_ENABLED": "true",
        "WEB_SEARCH_PROVIDER": "tavily",
        "WEB_SEARCH_API_KEY": "tvly-test",
        "WEB_SEARCH_MAX_RESULTS": "3",
        "WEB_SEARCH_TIMEOUT_SECONDS": "6",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert settings.web_search_enabled is True
        assert settings.web_search_provider == "tavily"
        assert settings.web_search_api_key == "tvly-test"
        assert settings.web_search_max_results == 3
        assert settings.web_search_timeout_seconds == 6


def test_settings_web_search_defaults_to_disabled():
    """验证联网搜索默认关闭，避免本地和测试环境意外访问外网

    返回:
        None；通过断言确认默认配置安全
    """
    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert settings.web_search_enabled is False
        assert settings.web_search_provider == "tavily"
        assert settings.web_search_api_key == ""
        assert settings.web_search_max_results == 5
        assert settings.web_search_timeout_seconds == 8
```

- [ ] **Step 2: Run config tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_config.py -q
```

Expected: new tests fail because `Settings` does not expose `web_search_*`.

- [ ] **Step 3: Implement config fields**

Add to `src/config.py` inside `Settings` after database config:

```python
    # 联网搜索配置；默认关闭，避免测试和本地开发意外访问外网
    web_search_enabled: bool = False
    web_search_provider: str = "tavily"
    web_search_api_key: str = ""
    web_search_max_results: int = 5
    web_search_timeout_seconds: int = 8
```

- [ ] **Step 4: Update `.env.example`**

Append after `DATABASE_URL=...`:

```env

# 联网搜索配置（默认关闭；启用后 search_web 工具可查询实时信息）
WEB_SEARCH_ENABLED=false
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_API_KEY=
WEB_SEARCH_MAX_RESULTS=5
WEB_SEARCH_TIMEOUT_SECONDS=8
```

- [ ] **Step 5: Write failing web search service tests**

Create `tests/test_web_search_service.py`:

```python
"""
联网搜索服务测试
验证 WebSearchService 在关闭、成功和 HTTP 失败时的行为

测试范围:
  - 默认关闭时不访问网络
  - Tavily 响应被归一化为 SearchResult
  - HTTP 异常时返回空列表而不是抛出
"""
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.mark.asyncio
async def test_web_search_returns_empty_when_disabled():
    """验证搜索关闭时直接返回空结果

    返回:
        None；通过断言确认不会调用 HTTP client
    """
    from src.search.service import WebSearchService

    post = AsyncMock()
    service = WebSearchService(
        enabled=False,
        api_key="",
        post_json=post,
    )

    results = await service.search("最新韩剧")

    assert results == []
    post.assert_not_called()


@pytest.mark.asyncio
async def test_web_search_normalizes_tavily_results():
    """验证 Tavily 搜索结果会归一化为 SearchResult 列表

    返回:
        None；通过断言确认标题、URL、摘要和分数被保留
    """
    from src.search.service import WebSearchService

    async def fake_post_json(url: str, payload: dict, timeout: int) -> dict:
        """模拟 Tavily API 返回

        参数:
            url: 请求 URL
            payload: JSON 请求体
            timeout: 超时秒数

        返回:
            dict: Tavily 风格响应
        """
        assert url == "https://api.tavily.com/search"
        assert payload["query"] == "最新韩剧"
        assert timeout == 8
        return {
            "results": [
                {
                    "title": "韩剧新闻",
                    "url": "https://example.test/kdrama",
                    "content": "一部新韩剧正在热播。",
                    "score": 0.9,
                }
            ]
        }

    service = WebSearchService(
        enabled=True,
        api_key="tvly-test",
        max_results=3,
        timeout_seconds=8,
        post_json=fake_post_json,
    )

    results = await service.search("最新韩剧")

    assert len(results) == 1
    assert results[0].title == "韩剧新闻"
    assert results[0].url == "https://example.test/kdrama"
    assert "热播" in results[0].snippet
    assert results[0].score == 0.9


@pytest.mark.asyncio
async def test_web_search_returns_empty_on_http_error():
    """验证联网搜索 HTTP 失败时返回空列表

    返回:
        None；通过断言确认工具层可以继续降级回答
    """
    from src.search.service import WebSearchService

    async def fake_post_json(url: str, payload: dict, timeout: int) -> dict:
        """模拟 HTTP 失败

        参数:
            url: 请求 URL
            payload: JSON 请求体
            timeout: 超时秒数

        返回:
            dict: 不会返回；总是抛出异常
        """
        raise httpx.HTTPError("network down")

    service = WebSearchService(
        enabled=True,
        api_key="tvly-test",
        post_json=fake_post_json,
    )

    results = await service.search("最新韩剧")

    assert results == []
```

- [ ] **Step 6: Run service tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_config.py tests/test_web_search_service.py -q
```

Expected: search tests fail because `src.search` does not exist.

- [ ] **Step 7: Implement search package**

Create `src/search/schemas.py`:

```python
"""
联网搜索数据结构
定义搜索服务返回给工具层的归一化结果对象

Workflow:
  WebSearchService.search() 调用外部供应商 → 解析结果 → 返回 SearchResult 列表
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    """联网搜索结果，供 search_web 工具格式化给 LLM"""

    title: str
    """搜索结果标题"""

    url: str
    """搜索结果 URL"""

    snippet: str
    """搜索结果摘要"""

    score: float | None = None
    """供应商返回的相关性分数；没有则为 None"""
```

Create `src/search/service.py`:

```python
"""
联网搜索服务
封装外部搜索 API 调用，将供应商响应归一化为 SearchResult 列表

Workflow:
  search() 检查配置 → 调用 Tavily 搜索 API → 解析 results → 返回 SearchResult
  搜索关闭、未配置 key 或 HTTP 失败时返回空列表，避免阻断主对话
"""
from collections.abc import Awaitable, Callable
import logging

import httpx

from src.config import settings
from src.search.schemas import SearchResult

logger = logging.getLogger(__name__)

PostJson = Callable[[str, dict, int], Awaitable[dict]]


class WebSearchService:
    """联网搜索服务，默认使用 Tavily API"""

    def __init__(
        self,
        enabled: bool | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        max_results: int | None = None,
        timeout_seconds: int | None = None,
        post_json: PostJson | None = None,
    ):
        """初始化搜索服务

        参数:
            enabled: 是否启用搜索；None 时读取 settings
            provider: 搜索供应商名称
            api_key: 搜索 API key
            max_results: 最多返回结果数
            timeout_seconds: HTTP 超时秒数
            post_json: 可选 HTTP 注入函数，测试时使用
        """
        self._enabled = settings.web_search_enabled if enabled is None else enabled
        self._provider = provider or settings.web_search_provider
        self._api_key = settings.web_search_api_key if api_key is None else api_key
        self._max_results = max_results or settings.web_search_max_results
        self._timeout_seconds = timeout_seconds or settings.web_search_timeout_seconds
        self._post_json = post_json

    async def search(self, query: str) -> list[SearchResult]:
        """搜索实时网页信息

        参数:
            query: 用户查询文本

        返回:
            list[SearchResult]: 归一化搜索结果；失败或未启用时为空列表
        """
        if not self._enabled or not self._api_key or not query.strip():
            return []
        if self._provider != "tavily":
            logger.warning("Unsupported web search provider: %s", self._provider)
            return []
        try:
            payload = {
                "api_key": self._api_key,
                "query": query,
                "max_results": self._max_results,
                "search_depth": "basic",
            }
            data = await self._post("https://api.tavily.com/search", payload)
            return self._parse_tavily_results(data)
        except httpx.HTTPError as e:
            logger.warning("Web search HTTP error: %s", e)
            return []

    async def _post(self, url: str, payload: dict) -> dict:
        """发送搜索 HTTP 请求

        参数:
            url: API URL
            payload: JSON 请求体

        返回:
            dict: 响应 JSON
        """
        if self._post_json is not None:
            return await self._post_json(url, payload, self._timeout_seconds)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    def _parse_tavily_results(self, data: dict) -> list[SearchResult]:
        """解析 Tavily 响应

        参数:
            data: Tavily JSON 响应

        返回:
            list[SearchResult]: 归一化结果
        """
        results = []
        for item in data.get("results", [])[:self._max_results]:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    score=item.get("score"),
                )
            )
        return results
```

Create `src/search/__init__.py`:

```python
"""联网搜索模块包，提供 WebSearchService 和 SearchResult"""
from src.search.schemas import SearchResult
from src.search.service import WebSearchService

__all__ = ["SearchResult", "WebSearchService"]
```

- [ ] **Step 8: Run config and search tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_config.py tests/test_web_search_service.py -q
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/config.py .env.example src/search tests/test_config.py tests/test_web_search_service.py
git commit -m "feat: add configurable web search service"
```

---

### Task 3: Add Butler Tool Wrappers

**Files:**
- Create: `src/agents/butler/__init__.py`
- Create: `src/agents/butler/tools.py`
- Create: `tests/test_butler_tools.py`

- [ ] **Step 1: Write failing tool wrapper tests**

Create `tests/test_butler_tools.py`:

```python
"""
Butler 工具层测试
验证 LangChain tools 能复用现有领域 agent、知识库服务和联网搜索服务

测试范围:
  - 领域工具调用现有 agent.handle()
  - 本地知识库检索工具格式化结果
  - 联网搜索工具格式化结果或给出未启用降级
"""
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import BaseTool

from src.schemas.response import AgentResponse


class FakeAgent:
    """测试用领域 agent，记录 handle 调用并返回固定响应"""

    def __init__(self, reply: str):
        """初始化 fake agent

        参数:
            reply: handle() 返回的回复文本
        """
        self.calls = []
        self._reply = reply

    async def handle(self, intent, message, user_id, db, extra_state=None):
        """记录领域 agent 调用

        参数:
            intent: 工具传入的意图
            message: 工具传入的消息
            user_id: 当前用户 ID
            db: 数据库会话
            extra_state: 会话上下文

        返回:
            AgentResponse: 固定测试响应
        """
        self.calls.append((intent, message, user_id, db, extra_state))
        return AgentResponse(reply=self._reply, data={"intent": intent})


def _find_tool(tools: list[BaseTool], name: str) -> BaseTool:
    """按名称查找工具

    参数:
        tools: 工具列表
        name: 工具名称

    返回:
        BaseTool: 匹配工具
    """
    return next(tool for tool in tools if tool.name == name)


@pytest.mark.asyncio
async def test_log_training_tool_calls_fitness_agent(db_session):
    """验证训练记录工具调用 FitnessAgent 的 log_training 路径

    参数:
        db_session: 测试数据库会话
    """
    from src.agents.butler.tools import ButlerToolContext, create_butler_tools

    fitness_agent = FakeAgent("已记录卧推")
    context = ButlerToolContext(
        fitness_agent=fitness_agent,
        meal_agent=FakeAgent("meal"),
        summary_agent=FakeAgent("summary"),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
    )
    tools = create_butler_tools(context)
    tool = _find_tool(tools, "log_training")

    result = await tool.ainvoke(
        {"message": "打卡 卧推80kg"},
        config={
            "configurable": {
                "db": db_session,
                "user_id": "assle",
                "chat_type": "single",
                "chat_id": None,
            }
        },
    )

    assert "已记录卧推" in result
    assert fitness_agent.calls[0][0] == "log_training"
    assert fitness_agent.calls[0][2] == "assle"


@pytest.mark.asyncio
async def test_search_web_tool_formats_results(db_session):
    """验证联网搜索工具会格式化标题、摘要和 URL

    参数:
        db_session: 测试数据库会话
    """
    from src.agents.butler.tools import ButlerToolContext, create_butler_tools
    from src.search.schemas import SearchResult

    web_search_service = AsyncMock()
    web_search_service.search.return_value = [
        SearchResult(
            title="韩剧新闻",
            url="https://example.test/kdrama",
            snippet="一部新韩剧正在热播。",
            score=0.9,
        )
    ]
    context = ButlerToolContext(
        fitness_agent=FakeAgent("fitness"),
        meal_agent=FakeAgent("meal"),
        summary_agent=FakeAgent("summary"),
        knowledge_service=AsyncMock(),
        web_search_service=web_search_service,
    )
    tool = _find_tool(create_butler_tools(context), "search_web")

    result = await tool.ainvoke(
        {"query": "最新韩剧"},
        config={"configurable": {"db": db_session, "user_id": "assle"}},
    )

    assert "韩剧新闻" in result
    assert "https://example.test/kdrama" in result
    assert "热播" in result


@pytest.mark.asyncio
async def test_search_web_tool_reports_no_results(db_session):
    """验证联网搜索无结果时返回可理解的降级文本

    参数:
        db_session: 测试数据库会话
    """
    from src.agents.butler.tools import ButlerToolContext, create_butler_tools

    web_search_service = AsyncMock()
    web_search_service.search.return_value = []
    context = ButlerToolContext(
        fitness_agent=FakeAgent("fitness"),
        meal_agent=FakeAgent("meal"),
        summary_agent=FakeAgent("summary"),
        knowledge_service=AsyncMock(),
        web_search_service=web_search_service,
    )
    tool = _find_tool(create_butler_tools(context), "search_web")

    result = await tool.ainvoke(
        {"query": "最新韩剧"},
        config={"configurable": {"db": db_session, "user_id": "assle"}},
    )

    assert "没有查到" in result or "未启用" in result
```

- [ ] **Step 2: Run tool tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_butler_tools.py -q
```

Expected: fails because `src.agents.butler.tools` does not exist.

- [ ] **Step 3: Implement tool context and tools**

Create `src/agents/butler/tools.py`:

```python
"""
ButlerAgent 工具定义
将现有领域 agent、知识库服务和联网搜索服务包装为 LangChain tools

Workflow:
  create_butler_tools() 接收运行期依赖 → 返回一组 async tools
  ToolNode 执行工具 → 工具从 config 读取 db/user/chat 上下文 → 调用现有业务边界
"""
from dataclasses import dataclass

from langchain_core.tools import tool
from langgraph.config import get_config


@dataclass
class ButlerToolContext:
    """Butler 工具运行依赖集合"""

    fitness_agent: object
    """健身领域 agent，提供训练记录和训练计划能力"""

    meal_agent: object
    """饮食领域 agent，提供食谱和饮食计划能力"""

    summary_agent: object
    """总结领域 agent，提供文本和群聊总结能力"""

    knowledge_service: object
    """知识库服务，提供本地知识检索能力"""

    web_search_service: object
    """联网搜索服务，提供实时网页检索能力"""


def _runtime() -> tuple[object, str, str, str | None]:
    """读取 LangGraph 工具运行上下文

    返回:
        tuple: (db, user_id, chat_type, chat_id)
    """
    configurable = get_config()["configurable"]
    return (
        configurable["db"],
        configurable["user_id"],
        configurable.get("chat_type", "single"),
        configurable.get("chat_id"),
    )


async def _call_agent(agent, intent: str, message: str) -> str:
    """调用现有领域 agent 并返回回复文本

    参数:
        agent: 实现 handle() 的领域 agent
        intent: 要传给领域 agent 的意图
        message: 用户消息或工具参数

    返回:
        str: 领域 agent 的回复文本
    """
    db, user_id, chat_type, chat_id = _runtime()
    result = await agent.handle(
        intent,
        message,
        user_id,
        db,
        extra_state={"chat_type": chat_type, "chat_id": chat_id},
    )
    return result.reply or "该工具没有生成有效结果。"


def create_butler_tools(context: ButlerToolContext):
    """创建 ButlerAgent 可用工具列表

    参数:
        context: 工具依赖集合

    返回:
        list: LangChain tools 列表
    """

    @tool
    async def log_training(message: str) -> str:
        """当用户想记录训练、健身打卡、保存训练数据时调用。message 必须是用户原始训练描述。"""
        return await _call_agent(context.fitness_agent, "log_training", message)

    @tool
    async def get_today_training_plan(message: str) -> str:
        """当用户询问今天练什么、训练建议、下一次训练安排时调用。message 必须是用户原始问题。"""
        return await _call_agent(context.fitness_agent, "today_plan", message)

    @tool
    async def make_meal_plan(message: str) -> str:
        """当用户询问吃什么、食谱、饮食计划、减脂增肌饮食时调用。message 必须是用户原始问题。"""
        return await _call_agent(context.meal_agent, "make_meal_plan", message)

    @tool
    async def summarize_text(text: str) -> str:
        """当用户要求总结一段明确提供的文本时调用。text 必须是需要总结的原文。"""
        return await _call_agent(context.summary_agent, "summarize_text", text)

    @tool
    async def summarize_group_chat(message: str) -> str:
        """当群聊中用户要求总结最近聊天记录时调用。message 必须是用户的总结请求。"""
        return await _call_agent(context.summary_agent, "summarize_group", message)

    @tool
    async def search_local_knowledge(query: str) -> str:
        """当用户问题可能需要本地知识库、项目资料、群聊私有资料或长期资料时调用。query 是检索问题。"""
        db, user_id, chat_type, chat_id = _runtime()
        results = await context.knowledge_service.search(
            query=query,
            user_id=user_id,
            db=db,
            chat_type=chat_type,
            chat_id=chat_id,
            domains=["global", "qa"],
            limit=5,
        )
        if not results:
            return "本地知识库没有查到相关资料。"
        blocks = []
        for index, item in enumerate(results, start=1):
            blocks.append(
                f"[{index}] {item.title} - {item.source}\\n{item.content}"
            )
        return "\\n\\n".join(blocks)

    @tool
    async def search_web(query: str) -> str:
        """当问题涉及最新、最近、今天、新闻、影视剧、价格、政策、版本等实时信息时调用。query 是联网搜索词。"""
        results = await context.web_search_service.search(query)
        if not results:
            return "联网搜索没有查到结果，或当前未启用联网搜索。"
        blocks = []
        for index, item in enumerate(results, start=1):
            blocks.append(
                f"[{index}] {item.title}\\nURL: {item.url}\\n摘要: {item.snippet}"
            )
        return "\\n\\n".join(blocks)

    return [
        log_training,
        get_today_training_plan,
        make_meal_plan,
        summarize_text,
        summarize_group_chat,
        search_local_knowledge,
        search_web,
    ]
```

Create `src/agents/butler/__init__.py`:

```python
"""Butler Agent 包，提供总控 tool-calling agent"""
```

- [ ] **Step 4: Run tool tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_butler_tools.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agents/butler tests/test_butler_tools.py
git commit -m "feat: add butler tool wrappers"
```

---

### Task 4: Implement ButlerAgent Graph

**Files:**
- Create: `src/agents/butler/state.py`
- Create: `src/agents/butler/prompts.py`
- Create: `src/agents/butler/nodes.py`
- Create: `src/agents/butler/graph.py`
- Modify: `src/agents/butler/__init__.py`
- Create: `tests/test_butler_agent.py`

- [ ] **Step 1: Write failing ButlerAgent graph tests**

Create `tests/test_butler_agent.py`:

```python
"""
ButlerAgent 图测试
验证总控 tool-calling agent 可以执行工具循环并保存对话记忆

测试范围:
  - 无工具调用时直接返回 LLM 回复
  - 有 search_web tool call 时执行 ToolNode 并生成最终回答
"""
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages.tool import ToolCall

from src.schemas.response import AgentResponse


class FakeToolCallingLLM:
    """测试用 LLM 客户端，按顺序返回预设 AIMessage"""

    def __init__(self, responses):
        """初始化 fake LLM

        参数:
            responses: 每次 ainvoke 后依次返回的 AIMessage 列表
        """
        self.responses = list(responses)
        self.calls = []

    def bind_tools(self, tools):
        """模拟绑定工具，返回自身

        参数:
            tools: 工具列表

        返回:
            FakeToolCallingLLM: 自身
        """
        self.tools = tools
        return self

    async def ainvoke(self, messages, **kwargs):
        """模拟 LangChain runnable 调用

        参数:
            messages: 当前图消息
            kwargs: 调用参数

        返回:
            AIMessage: 预设响应
        """
        self.calls.append(messages)
        return self.responses.pop(0)

    async def chat(self, messages, model=None, temperature=0.7):
        """兼容 ConversationMemory 压缩调用

        参数:
            messages: 聊天消息
            model: 模型名
            temperature: 温度

        返回:
            str: 固定摘要
        """
        return "摘要"


class FakeAgent:
    """测试用领域 agent"""

    async def handle(self, intent, message, user_id, db, extra_state=None):
        """返回固定 agent 响应

        参数:
            intent: 意图
            message: 用户消息
            user_id: 用户 ID
            db: 数据库会话
            extra_state: 额外状态

        返回:
            AgentResponse: 固定回复
        """
        return AgentResponse(reply=f"{intent}:{message}")


@pytest.mark.asyncio
async def test_butler_agent_returns_direct_llm_answer(db_session):
    """验证无工具调用时 ButlerAgent 直接返回 LLM 回复

    参数:
        db_session: 测试数据库会话
    """
    from src.agents.butler.graph import ButlerAgent

    llm = FakeToolCallingLLM([AIMessage(content="你好，我在。")])
    agent = ButlerAgent(
        llm_client=llm,
        fitness_agent=FakeAgent(),
        meal_agent=FakeAgent(),
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
    )

    result = await agent.handle("butler", "你好", "assle", db_session)

    assert result.reply == "你好，我在。"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_butler_agent_executes_web_search_tool(db_session):
    """验证 ButlerAgent 能执行 LLM 请求的 search_web 工具

    参数:
        db_session: 测试数据库会话
    """
    from src.agents.butler.graph import ButlerAgent
    from src.search.schemas import SearchResult

    first = AIMessage(
        content="",
        tool_calls=[
            ToolCall(
                name="search_web",
                args={"query": "最新韩剧"},
                id="call-1",
            )
        ],
    )
    second = AIMessage(content="查到了：一部新韩剧正在热播。")
    web_search_service = AsyncMock()
    web_search_service.search.return_value = [
        SearchResult(
            title="韩剧新闻",
            url="https://example.test/kdrama",
            snippet="一部新韩剧正在热播。",
            score=0.9,
        )
    ]
    llm = FakeToolCallingLLM([first, second])
    agent = ButlerAgent(
        llm_client=llm,
        fitness_agent=FakeAgent(),
        meal_agent=FakeAgent(),
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=web_search_service,
    )

    result = await agent.handle("butler", "最近有什么韩剧？", "assle", db_session)

    assert "热播" in result.reply
    web_search_service.search.assert_awaited_once_with("最新韩剧")
    assert len(llm.calls) == 2
```

- [ ] **Step 2: Run ButlerAgent tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_butler_agent.py -q
```

Expected: fails because `src.agents.butler.graph` does not exist.

- [ ] **Step 3: Implement Butler state and prompt**

Create `src/agents/butler/state.py`:

```python
"""
ButlerAgent 状态定义
定义总控 tool-calling 图中所有节点共享的状态字段

Workflow:
  HumanMessage → agent 节点生成 AIMessage → ToolNode 执行工具 → agent 节点生成最终回复
"""
from typing import Annotated, Optional

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class ButlerState(TypedDict, total=False):
    """ButlerAgent 状态字典，包含 tool-calling 图执行所需字段"""

    messages: Annotated[list[AnyMessage], add_messages]
    """LangGraph 消息列表，使用 add_messages 自动追加 AIMessage 和 ToolMessage"""

    user_id: str
    """当前用户 ID"""

    chat_type: str
    """会话类型，single 或 group"""

    chat_id: Optional[str]
    """群聊 ID，私聊为 None"""

    conversation_summary: Optional[str]
    """早期对话压缩摘要"""

    recent_messages: list[dict]
    """最近对话记录"""

    reply: str
    """最终回复文本"""

    error: Optional[str]
    """执行错误信息"""
```

Create `src/agents/butler/prompts.py`:

```python
"""
ButlerAgent prompt 定义
集中维护总控 tool-calling agent 的系统提示词

Workflow:
  nodes.py 调用 build_system_prompt() → 注入对话记忆 → LLM 根据工具说明决定是否调用工具
"""
BUTLER_SYSTEM_PROMPT = """你是“小管家”，用户的私人 AI 助理。

你需要理解用户目标，并在需要时调用工具完成任务。

工具使用规则：
- 能直接闲聊或解释的问题，可以直接回答。
- 涉及训练打卡、保存训练数据时，调用训练记录工具。
- 涉及今天练什么、训练建议时，调用训练计划工具。
- 涉及吃什么、食谱、饮食计划时，调用饮食工具。
- 涉及总结一段文本或群聊历史时，调用总结工具。
- 涉及本地资料、项目资料、群聊私有资料时，调用本地知识库工具。
- 涉及最新、最近、今天、新闻、影视剧、价格、政策、软件版本等实时信息时，调用联网搜索工具。

回答规则：
- 不要编造工具结果；工具没有结果时明确说明。
- 工具结果是事实依据，最终回答要自然、简洁，必要时附来源 URL。
- 不要向用户暴露内部工具名，除非用户询问系统实现。
- 语气温暖自然，像熟悉的朋友，不要客服腔。

历史对话：
{conversation_context}
"""


def build_system_prompt(conversation_summary: str | None, recent_messages: list[dict]) -> str:
    """构建 ButlerAgent 系统提示词

    参数:
        conversation_summary: 压缩后的早期对话摘要
        recent_messages: 最近对话消息

    返回:
        str: 完整 system prompt
    """
    parts = []
    if conversation_summary:
        parts.append(f"早期对话摘要：{conversation_summary}")
    if recent_messages:
        parts.append("最近几轮对话会以消息形式提供。")
    conversation_context = "\\n".join(parts) if parts else "暂无历史对话。"
    return BUTLER_SYSTEM_PROMPT.format(conversation_context=conversation_context)
```

- [ ] **Step 4: Implement nodes and graph**

Create `src/agents/butler/nodes.py`:

```python
"""
ButlerAgent 节点函数
负责调用绑定工具后的 LLM，并在图结束前提取最终回复

Workflow:
  call_model() → 根据 AIMessage.tool_calls 条件进入 ToolNode 或结束
  extract_reply() → 从最后一条 AIMessage 中提取最终回复文本
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.config import get_config

from src.agents.butler.prompts import build_system_prompt


async def call_model(state: dict) -> dict:
    """调用绑定工具后的 LLM

    参数:
        state: 当前 ButlerState，包含 messages 和对话上下文

    返回:
        dict: {"messages": [AIMessage]}，供 LangGraph 追加
    """
    configurable = get_config()["configurable"]
    llm = configurable["llm"]
    tools = configurable["tools"]
    system = SystemMessage(
        content=build_system_prompt(
            state.get("conversation_summary"),
            state.get("recent_messages", []),
        )
    )
    messages = [system]
    for msg in state.get("recent_messages", []):
        messages.append(msg)
    messages.extend(state["messages"])
    response = await llm.bind_tools(tools).ainvoke(messages)
    return {"messages": [response]}


async def extract_reply(state: dict) -> dict:
    """从图消息中提取最终回复文本

    参数:
        state: 当前 ButlerState

    返回:
        dict: {"reply": "..."}
    """
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) and not message.tool_calls:
            content = message.content
            return {"reply": content if isinstance(content, str) else str(content)}
    return {"reply": "抱歉，我这次没有生成有效回复。"}


def build_initial_messages(message: str) -> list[HumanMessage]:
    """构建图初始用户消息

    参数:
        message: 用户原始消息

    返回:
        list[HumanMessage]: 初始消息列表
    """
    return [HumanMessage(content=message)]
```

Create `src/agents/butler/graph.py`:

```python
"""
Butler Agent - 总控 tool-calling StateGraph
负责让 LLM 自主决定是否调用训练、饮食、总结、知识库和联网搜索工具

Workflow:
  handle() 加载对话记忆 → agent 节点调用 bound LLM → ToolNode 执行工具
  → agent 节点生成最终回复 → extract_reply → 保存对话记忆 → AgentResponse
"""
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from src.agents.butler.nodes import build_initial_messages, call_model, extract_reply
from src.agents.butler.state import ButlerState
from src.agents.butler.tools import ButlerToolContext, create_butler_tools
from src.graph.memory import checkpointer as _checkpointer
from src.llm.client import LLMClient
from src.memory.conversation import ConversationMemory
from src.schemas.response import AgentResponse


class ButlerAgent:
    """总控 tool-calling agent，接管可回复消息的主执行入口"""

    def __init__(
        self,
        llm_client: LLMClient,
        fitness_agent,
        meal_agent,
        summary_agent,
        knowledge_service,
        web_search_service,
    ):
        """初始化 ButlerAgent 并编译工具调用图

        参数:
            llm_client: LLM 客户端
            fitness_agent: 健身领域 agent
            meal_agent: 饮食领域 agent
            summary_agent: 总结领域 agent
            knowledge_service: 知识库服务
            web_search_service: 联网搜索服务
        """
        self._llm = llm_client
        self._tool_context = ButlerToolContext(
            fitness_agent=fitness_agent,
            meal_agent=meal_agent,
            summary_agent=summary_agent,
            knowledge_service=knowledge_service,
            web_search_service=web_search_service,
        )
        self._tools = create_butler_tools(self._tool_context)
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 ButlerAgent StateGraph

        返回:
            CompiledStateGraph: 带 ToolNode 的总控图
        """
        builder = StateGraph(ButlerState)
        builder.add_node("agent", call_model)
        builder.add_node("tools", ToolNode(self._tools))
        builder.add_node("extract_reply", extract_reply)

        builder.add_edge(START, "agent")
        builder.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "tools", END: "extract_reply"},
        )
        builder.add_edge("tools", "agent")
        builder.add_edge("extract_reply", END)
        return builder.compile(checkpointer=_checkpointer)

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理用户消息

        参数:
            intent: 兼容旧 agent 接口，ButlerAgent 通常传入 "butler"
            message: 用户原始消息
            user_id: 用户 ID
            db: SQLAlchemy 异步数据库会话
            extra_state: 可选会话上下文，包含 chat_type/chat_id

        返回:
            AgentResponse: 最终自然语言回复
        """
        chat_type = "single"
        chat_id = None
        if extra_state:
            chat_type = extra_state.get("chat_type", chat_type)
            chat_id = extra_state.get("chat_id")

        memory = ConversationMemory(self._llm)
        summary, recent = await memory.get_context(user_id, db)
        initial_state: dict = {
            "messages": build_initial_messages(message),
            "user_id": user_id,
            "chat_type": chat_type,
            "chat_id": chat_id,
            "conversation_summary": summary,
            "recent_messages": recent,
        }
        config = {
            "configurable": {
                "db": db,
                "llm": self._llm,
                "tools": self._tools,
                "thread_id": f"butler:{user_id}",
                "user_id": user_id,
                "chat_type": chat_type,
                "chat_id": chat_id,
            },
            "recursion_limit": 8,
        }
        try:
            result = await self._graph.ainvoke(initial_state, config)
            reply = result.get("reply", "")
        except Exception:
            reply = "LLM 服务暂时不可用，请稍后重试。"
        await memory.save_exchange(user_id, message, reply, db)
        return AgentResponse(reply=reply, data={"intent": "butler"})
```

Update `src/agents/butler/__init__.py`:

```python
"""Butler Agent 包，提供总控 tool-calling agent"""
from src.agents.butler.graph import ButlerAgent

__all__ = ["ButlerAgent"]
```

- [ ] **Step 5: Run ButlerAgent tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_butler_agent.py tests/test_butler_tools.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/agents/butler tests/test_butler_agent.py
git commit -m "feat: add tool-calling butler agent"
```

---

### Task 5: Wire ButlerAgent Into Main And Debug Route

**Files:**
- Modify: `src/main.py`
- Modify: `src/router/debug.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Update failing API tests**

Modify `tests/test_api.py` so the private chat tests patch `src.main.butler_agent.handle` instead of LLM routing. Replace the two existing tests with:

```python
@pytest.mark.asyncio
async def test_debug_endpoint_private_message_uses_butler_agent(http_client):
    """验证调试端点私聊消息进入 ButlerAgent

    参数:
        http_client: httpx 异步客户端 fixture
    """
    from src.schemas.response import AgentResponse

    with patch.object(
        src.main.butler_agent,
        "handle",
        return_value=AgentResponse(reply="你好！有什么可以帮你的？", data={"intent": "butler"}),
    ) as mock_handle:
        response = await http_client.post(
            "/api/debug/message",
            json={"user_id": "assle", "message": "你好"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "butler"
    assert body["confidence"] == 1.0
    assert body["response"] == "你好！有什么可以帮你的？"
    mock_handle.assert_awaited_once()
    assert mock_handle.call_args.args[:4] == ("butler", "你好", "assle")


@pytest.mark.asyncio
async def test_debug_endpoint_group_non_trigger_still_collects_only(http_client):
    """验证群聊非触发消息仍然只收集不调用 ButlerAgent

    参数:
        http_client: httpx 异步客户端 fixture
    """
    with patch.object(src.main.butler_agent, "handle") as mock_handle:
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "普通群聊消息",
                "chat_type": "group",
                "chat_id": "chat-a",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "collect_group"
    assert body["response"] == ""
    mock_handle.assert_not_called()


@pytest.mark.asyncio
async def test_debug_endpoint_group_trigger_uses_butler_agent(http_client):
    """验证群聊触发消息进入 ButlerAgent 并传入群聊上下文

    参数:
        http_client: httpx 异步客户端 fixture
    """
    from src.schemas.response import AgentResponse

    with patch.object(
        src.main.butler_agent,
        "handle",
        return_value=AgentResponse(reply="群聊总结完成", data={"intent": "butler"}),
    ) as mock_handle:
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "总结一下",
                "chat_type": "group",
                "chat_id": "chat-a",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "butler"
    assert body["response"] == "群聊总结完成"
    assert mock_handle.call_args.args[:4] == ("butler", "总结一下", "assle")
    assert mock_handle.call_args.kwargs["extra_state"] == {
        "chat_id": "chat-a",
        "chat_type": "group",
    }
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_api.py -q
```

Expected: fails because `src.main.butler_agent` is not wired and route still uses `IntentRouter`.

- [ ] **Step 3: Wire ButlerAgent in `src/main.py`**

Modify imports and singleton setup:

```python
from src.agents.butler import ButlerAgent
from src.knowledge.service import KnowledgeService
from src.search.service import WebSearchService
```

After `qa_agent = QAAgent(...)`:

```python
knowledge_service = KnowledgeService()
web_search_service = WebSearchService()
butler_agent = ButlerAgent(
    llm_client=llm_client,
    fitness_agent=fitness_agent,
    meal_agent=meal_agent,
    summary_agent=summary_agent,
    knowledge_service=knowledge_service,
    web_search_service=web_search_service,
)
```

Change debug router construction:

```python
debug_router = create_debug_router(
    intent_router=intent_router,
    agent_registry=agent_registry,
    butler_agent=butler_agent,
)
```

- [ ] **Step 4: Update debug router**

Change `create_debug_router()` signature in `src/router/debug.py`:

```python
def create_debug_router(
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    butler_agent,
) -> APIRouter:
```

For group trigger branch, replace `agent_registry.get("summarize_group")` and `agent.handle(...)` with:

```python
            try:
                result = await butler_agent.handle(
                    "butler", req.message, req.user_id, db,
                    extra_state={"chat_id": req.chat_id, "chat_type": "group"},
                )
                return DebugMessageResponse(
                    intent="butler",
                    confidence=1.0,
                    response=result.reply,
                    data=result.data,
                )
            except APIError as e:
                return DebugMessageResponse(
                    intent="butler",
                    confidence=1.0,
                    response="LLM 服务暂时不可用，请稍后重试。",
                    data={"error": str(e)},
                )
```

For private chat branch, replace intent routing with:

```python
        try:
            result = await butler_agent.handle(
                "butler",
                req.message,
                req.user_id,
                db,
                extra_state={"chat_type": req.chat_type, "chat_id": req.chat_id or None},
            )
        except APIError as e:
            return DebugMessageResponse(
                intent="butler",
                confidence=1.0,
                response="LLM 服务暂时不可用，请稍后重试。",
                data={"error": str(e)},
            )

        return DebugMessageResponse(
            intent="butler",
            confidence=1.0,
            response=result.reply,
            data=result.data,
        )
```

Keep `intent_router` and `agent_registry` parameters for compatibility during this task; remove them only in a later cleanup task if all callers no longer need them.

- [ ] **Step 5: Run API tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_api.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/main.py src/router/debug.py tests/test_api.py
git commit -m "feat: route debug messages through butler agent"
```

---

### Task 6: Wire ButlerAgent Into WeChat Handlers

**Files:**
- Modify: `src/wechat/callback_handler.py`
- Modify: `src/wechat/callback_router.py`
- Modify: `src/wechat/message_handler.py`
- Modify: `src/main.py`
- Modify: `tests/test_aibot_callback.py`

- [ ] **Step 1: Update callback handler tests**

In `tests/test_aibot_callback.py`, add fixture:

```python
@pytest.fixture
def mock_butler_agent():
    """创建测试用 ButlerAgent

    返回:
        AsyncMock: handle() 固定返回 mock reply
    """
    from src.schemas.response import AgentResponse

    agent = AsyncMock()
    agent.handle.return_value = AgentResponse(reply="mock butler reply", data={"intent": "butler"})
    return agent
```

Update `test_handle_callback_message_posts_reply_to_response_url` to pass `mock_butler_agent` and assert posted content is `"mock butler reply"`:

```python
async def test_handle_callback_message_posts_reply_to_response_url(
    db_session,
    mock_intent_router,
    mock_agent_registry,
    mock_butler_agent,
):
    ...
    await handle_callback_message(
        msg,
        reply_client,
        mock_intent_router,
        mock_agent_registry,
        mock_butler_agent,
        db_session,
    )
    ...
    assert posted == [
        (
            "https://example.test/respond",
            {"msgtype": "markdown", "markdown": {"content": "mock butler reply"}},
        )
    ]
    mock_butler_agent.handle.assert_awaited_once()
```

Add group non-trigger test:

```python
@pytest.mark.asyncio
async def test_handle_callback_message_group_non_trigger_does_not_call_butler(
    db_session,
    mock_intent_router,
    mock_agent_registry,
    mock_butler_agent,
):
    """验证群聊非触发消息仍静默收集，不调用 ButlerAgent

    参数:
        db_session: 测试数据库会话
        mock_intent_router: 模拟意图路由器
        mock_agent_registry: 模拟 agent 注册表
        mock_butler_agent: 模拟 ButlerAgent
    """
    from src.wechat.callback_handler import ResponseUrlReplyClient, handle_callback_message

    posted = []

    async def fake_post_json(url: str, payload: dict) -> bool:
        """记录发送请求

        参数:
            url: response_url
            payload: 消息体

        返回:
            bool: 模拟成功
        """
        posted.append((url, payload))
        return True

    msg = {
        "msgid": "msg-group-1",
        "msgtype": "text",
        "from": {"userid": "user1"},
        "text": {"content": "普通群聊"},
        "chattype": "group",
        "chatid": "chat-a",
        "response_url": "https://example.test/respond",
    }

    await handle_callback_message(
        msg,
        ResponseUrlReplyClient(post_json=fake_post_json),
        mock_intent_router,
        mock_agent_registry,
        mock_butler_agent,
        db_session,
    )

    assert posted == []
    mock_butler_agent.handle.assert_not_called()
```

- [ ] **Step 2: Run callback tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_aibot_callback.py -q
```

Expected: fails because `handle_callback_message()` and router factories do not accept `butler_agent`.

- [ ] **Step 3: Update callback handler signatures and logic**

In `src/wechat/callback_handler.py`:

```python
async def handle_callback_message(
    msg: dict,
    reply_client: ResponseUrlReplyClient,
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    butler_agent,
    db: AsyncSession,
):
```

Update docstring to describe `butler_agent`.

Change `_build_reply_text()` signature:

```python
async def _build_reply_text(
    msg_type: str,
    content: str,
    from_user: str,
    db: AsyncSession,
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    butler_agent,
    extra_state: dict,
    is_group_trigger: bool,
) -> str:
```

Inside `_build_reply_text()`, keep unsupported message check first, then route all replyable text/voice messages through ButlerAgent:

```python
    if msg_type not in ("text", "voice"):
        return "暂不支持该消息类型"
    try:
        result = await butler_agent.handle(
            "butler",
            content,
            from_user,
            db,
            extra_state=extra_state,
        )
        return result.reply
    except Exception as e:
        logger.exception("AIBot callback: butler agent error: %s", e)
        return "LLM 服务暂时不可用，请稍后重试。"
```

Keep `intent_router`, `agent_registry`, and `is_group_trigger` parameters temporarily for compatibility and tests; `is_group_trigger` remains meaningful because non-trigger group messages return before `_build_reply_text()`.

- [ ] **Step 4: Update callback router**

In `src/wechat/callback_router.py`, add `butler_agent` to `create_aibot_callback_router()` and `process_recorded_message()` signatures.

When adding background task:

```python
                butler_agent,
                db_session_factory,
```

When calling `handle_callback_message()`:

```python
            await handle_callback_message(
                msg,
                reply_client,
                intent_router,
                agent_registry,
                butler_agent,
                db,
            )
```

- [ ] **Step 5: Update main callback wiring**

In `src/main.py`, pass `butler_agent=butler_agent` to `create_aibot_callback_router(...)`.

- [ ] **Step 6: Update legacy WebSocket handler**

In `src/wechat/message_handler.py`, add `butler_agent` parameter after `agent_registry`. For replyable text/voice messages, replace intent routing and group summary direct call with:

```python
        try:
            result = await butler_agent.handle(
                "butler",
                content,
                from_user,
                db,
                extra_state=extra_state,
            )
            reply_text = result.reply
        except Exception as e:
            logger.exception("WS handler: butler agent error: %s", e)
            reply_text = "LLM 服务暂时不可用，请稍后重试。"
```

Keep group non-trigger return and unsupported message behavior unchanged.

- [ ] **Step 7: Run callback tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_aibot_callback.py -q
```

Expected: tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/wechat/callback_handler.py src/wechat/callback_router.py src/wechat/message_handler.py src/main.py tests/test_aibot_callback.py
git commit -m "feat: route wechat replies through butler agent"
```

---

### Task 7: Update Documentation And Architecture Memory Docs

**Files:**
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/decisions.md`
- Modify: `docs/agent/config-variables.md`
- Modify: `docs/agent/troubleshooting.md`
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update active context**

In `docs/agent/active-context.md`, change the current state paragraph to say the app dispatches replyable messages through `ButlerAgent`, whose tools wrap the existing domain agents. Add a bullet:

```markdown
- Main reply path: `ButlerAgent` LangGraph tool-calling loop; LLM decides when to call training, meal, summary, local knowledge, or web search tools.
```

- [ ] **Step 2: Update patterns**

Add a section to `docs/agent/patterns.md`:

```markdown
## Butler Tool-Calling Pattern

Replyable private messages and trigger-style group messages enter `ButlerAgent`.
`ButlerAgent` owns the LangGraph `ToolNode` loop and exposes existing capabilities as tools instead of duplicating business logic.

Rules:
- Tools read `db`, `user_id`, `chat_type`, and `chat_id` from LangGraph config, not from model-supplied arguments.
- Tool functions return short text; they do not return `AgentResponse` objects.
- Existing domain agents remain the source of truth for training, meal, and summary workflows.
- Group non-trigger messages stay outside ButlerAgent and are collected silently.
```

- [ ] **Step 3: Update decisions**

Append an ADR to `docs/agent/decisions.md`:

```markdown
## ADR-014: ButlerAgent Tool-Calling Main Entry

Replyable user messages now enter a total-control `ButlerAgent` that binds LangChain tools to the LLM and executes them through LangGraph `ToolNode`.

Reasoning:
- The previous route-first model was stable but made every new capability depend on intent classification.
- Tool calling lets the LLM choose when to use local knowledge, web search, training, meal, and summary tools.
- Existing domain agents remain reusable behind tools, so business logic is not duplicated.
- Group non-trigger collection stays deterministic to avoid LLM work for every group message.

Trade-off:
- One user message can involve multiple LLM calls, increasing latency and cost.
- Tool descriptions and tests are now part of behavior control.
- DeepSeek tool-calling compatibility should be manually smoke-tested with a real key after unit tests pass.
```

- [ ] **Step 4: Update config docs**

In `docs/agent/config-variables.md`, add the web search table from the spec:

```markdown
## 联网搜索

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `WEB_SEARCH_ENABLED` | No | `false` | Whether the `search_web` tool can call the external search provider |
| `WEB_SEARCH_PROVIDER` | No | `tavily` | Search provider; first implementation supports Tavily |
| `WEB_SEARCH_API_KEY` | No | `""` | API key for the selected search provider |
| `WEB_SEARCH_MAX_RESULTS` | No | `5` | Maximum result count returned to the LLM |
| `WEB_SEARCH_TIMEOUT_SECONDS` | No | `8` | HTTP timeout for search requests |
```

- [ ] **Step 5: Update troubleshooting**

Append to `docs/agent/troubleshooting.md`:

```markdown
## ButlerAgent Tool Calling Does Not Use A Tool

Symptom:
- The assistant answers from memory when it should call training, summary, knowledge, or web search tools.

Checks:
- Inspect `src/agents/butler/prompts.py` for tool-use policy.
- Inspect tool descriptions in `src/agents/butler/tools.py`.
- Confirm the model supports tool calls through the configured DeepSeek-compatible endpoint.

Fix:
- Tighten the relevant tool description and add a focused ButlerAgent test with a fake `AIMessage.tool_calls`.

## Web Search Tool Returns No Results

Symptom:
- The assistant says web search is not enabled or no results were found.

Checks:
- Confirm `WEB_SEARCH_ENABLED=true`.
- Confirm `WEB_SEARCH_API_KEY` is set locally and not committed.
- Confirm provider is `tavily`.
- Check logs for `Web search HTTP error`.

Fix:
- Set the missing env var or retry after provider/network recovery.
```

- [ ] **Step 6: Update CLAUDE.md and AGENTS.md if needed**

If either root file describes the main routing flow as `IntentRouter → AgentRegistry → agent`, update both files with the same wording:

```markdown
- Current reply path: replyable private messages and trigger-style group messages enter `ButlerAgent`, a LangGraph tool-calling agent. `IntentRouter` and `AgentRegistry` remain available for compatibility and domain agent reuse, but they are no longer the default main entry for replyable messages.
```

After editing, verify they are identical:

```bash
cmp -s CLAUDE.md AGENTS.md && echo "root docs identical"
```

Expected output:

```text
root docs identical
```

- [ ] **Step 7: Run doc consistency checks**

Run:

```bash
rg -n "IntentRouter.*AgentRegistry|route\\(\\).*registry|get\\(intent\\)" docs/agent CLAUDE.md AGENTS.md
cmp -s CLAUDE.md AGENTS.md && echo "root docs identical"
```

Expected: search results are either historical/compatibility references or updated to mention ButlerAgent; `cmp` prints `root docs identical`.

- [ ] **Step 8: Commit**

```bash
git add docs/agent/active-context.md docs/agent/patterns.md docs/agent/decisions.md docs/agent/config-variables.md docs/agent/troubleshooting.md CLAUDE.md AGENTS.md
git commit -m "docs: document butler tool-calling entry"
```

---

### Task 8: Full Verification And Compatibility Fixes

**Files:**
- Modify only files needed to fix failures found by the commands below.

- [ ] **Step 1: Run focused test groups**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_llm.py \
  tests/test_config.py \
  tests/test_web_search_service.py \
  tests/test_butler_tools.py \
  tests/test_butler_agent.py \
  tests/test_api.py \
  tests/test_aibot_callback.py \
  -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run existing agent tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_qa.py \
  tests/test_knowledge_service.py \
  tests/test_intent.py \
  tests/test_scheduler.py \
  tests/test_smoke.py \
  tests/test_e2e_group_summary.py \
  -q
```

Expected: existing agent, knowledge, intent, scheduler, smoke, and group summary tests pass.

- [ ] **Step 3: Run full test suite**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: full test suite passes.

- [ ] **Step 4: Inspect worktree**

Run:

```bash
git status --short
git diff --stat
```

Expected: only intentional implementation and documentation files are modified. Do not remove unrelated pre-existing `.idea` or SQLite WAL/SHM files unless the user explicitly asks.

- [ ] **Step 5: Commit final fixes if any**

If Step 1-3 required fixes not already committed:

```bash
git add <only-files-you-changed-for-this-task>
git commit -m "fix: stabilize butler tool-calling integration"
```

If there were no fixes after Task 7, skip this commit.

---

## Self-Review

- Spec coverage:
  - Main entry moves to ButlerAgent: Tasks 4, 5, and 6.
  - Deterministic group protection: Tasks 5 and 6.
  - Tool catalog wrapping existing capabilities: Task 3.
  - Web search as a tool: Tasks 2 and 3.
  - LLM tool-call support: Task 1.
  - Documentation and ADR updates: Task 7.
  - Verification: Task 8.
- Placeholder scan: no `TBD`, `TODO`, or open-ended implementation placeholders are intentionally present.
- Type consistency:
  - ButlerAgent uses `handle(intent, message, user_id, db, extra_state=None)` to match existing `GraphAgent`.
  - Tool wrappers return `str`.
  - `WebSearchService.search()` returns `list[SearchResult]`.
  - Debug route returns `DebugMessageResponse(intent="butler", confidence=1.0, ...)`.
