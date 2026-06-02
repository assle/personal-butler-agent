# LangGraph迁移设计

## 目的

重构当前的 MVP，采用 LangChain + LangGraph 作为智能体框架，同时保留现有的 FastAPI 表面、SQLite 持久性和调试端点契约。主要动机是：(1) 使项目的技术堆栈与当前代理开发面试期望保持一致，(2) 为未来模块（多轮内存、RAG、计划任务、研究助理等）建立更清晰的扩展模式，而不会使当前工作代码过于复杂。

## 架构概述

### 堆

- **HTTP层**：FastAPI（保持不变）
- **LLM 访问**：`langchain_openai.ChatOpenAI` 指向 DeepSeek（替换 `openai.AsyncOpenAI`）
- **智能体编排**：每个域代理的 LangGraph `StateGraph`
- **持久化**：SQLAlchemy 2 异步 + SQLite（保持不变）
- **调度**：APScheduler（已经在 deps 中，稍后连接）

### 项目结构（目标）

```
src/
├── main.py              # FastAPI lifespan, dependency wiring (minor edits)
├── config.py             # pydantic-settings (add langchain-specific keys)
├── router/
│   └── debug.py          # HTTP route, intent dispatch via registry (thinned)
├── intent/
│   ├── router.py         # IntentRouter: rule-first + ChatModel fallback
│   └── rules.py          # keyword matching (unchanged)
├── agents/
│   ├── registry.py       # intent → graph agent central registry
│   ├── base.py           # BaseGraphAgent ABC: compile + run
│   ├── fitness/
│   │   ├── state.py      # FitnessState TypedDict
│   │   ├── nodes.py      # node functions (single-responsibility)
│   │   └── graph.py      # StateGraph assembly + compile
│   ├── summary/          # same pattern
│   ├── meal/
│   └── qa/
├── graph/
│   ├── common.py         # shared state fields, common nodes (error_handler)
│   └── memory.py         # MemorySaver / SqliteSaver checkpoint config
├── llm/
│   └── client.py         # ChatOpenAI wrapper (DeepSeek-compatible)
├── models/               # SQLAlchemy ORM (unchanged)
├── schemas/              # Pydantic request/response (unchanged)
└── db/                   # engine, session, base (unchanged)
```

### 什么保持不变

- `POST /api/debug/message` 请求/响应架构
- SQLAlchemy ORM 模型和 `AsyncSession` 注入模式
- 基于关键字的规则匹配进行意图分类
- `AgentResponse` / `DebugMessageResponse` 悬垂类型
- 测试策略：模拟LLM客户端，隔离数据库引擎

## LangGraph 代理模式

每个域代理都成为具有类型化状态和单一用途节点的 `StateGraph`。代理的 `handle()` 方法构建初始状态并运行图表 - 调用者看不到任何差异。

### 状态定义（示例：FitnessAgent）

```python
class FitnessState(TypedDict):
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

### 节点映射（FitnessAgent）

| 小路           | 节点                                                              |
|----------------|--------------------------------------------------------------------|
| `log_training` | 提取→验证→保留→格式化                             |
| `today_plan`   | fetch_history→fetch_preferences→generate_plan→format_response |

### 图拓扑

```
    __start__
        │
    [classify]  ← condition edge by intent
     /      \
log_training  today_plan
  │ extract      │ fetch_history
  │ validate     │ fetch_preferences
  │ persist      │ generate_plan
  │ format       │ format
     \      /
    __end__
```

### 错误处理

每个LLM调用节点捕获异常并设置`error`字段。条件边缘检查错误并路由到格式化降级响应的公共 `error_handler` 节点。 LLM 不可用永远不会导致请求崩溃。

## 数据流

```
POST /api/debug/message
  │
  ▼
IntentRouter.route(message)
  ├── rules.py match → (intent, 1.0)
  └── no match → ChatModel classify → (intent, confidence)
  │
  ▼
registry.get(intent) → compiled GraphAgent
  │
  ▼
agent.handle(intent, message, user_id, db)
  ├── initial_state = {intent, message, user_id, ...}
  ├── graph.ainvoke(state, config={"configurable": {"thread_id": user_id}})
  └── extract reply + data → AgentResponse
  │
  ▼
DebugMessageResponse
```

## 内存支持

LangGraph 的检查点以接近零的自定义代码提供多轮对话记忆。

- **MVP 阶段**：`MemorySaver`（内存中，重新启动之间没有持久性）。
- **后 MVP**：切换到由 SQLite 支持的 `SqliteSaver`，相同的 `thread_id = user_id` 密钥。
- 需要历史记录的代理参考由较早轮次填充的先前状态字段。
- 每个域隔离：健身对话不会泄漏到膳食计划对话中。

## 扩展点

| 特征               | 如何插入                                                            |
|-----------------------|----------------------------------------------------------------------------|
| 新代理人（例如研究） | `agents/research/` → 状态 + 节点 + 图 → 寄存器到 `registry.py` |
| 多圈记忆     | 交换 `MemorySaver` → `SqliteSaver`，不更改代理代码                  |
| 抹布                   | 使用LangChain文档加载器+向量存储添加`retrieve`节点         |
| 计划任务       | APScheduler 作业直接调用`agent.handle()`，相同的图路径           |
| 消息摘要 | 当前`SummaryAgent`改写为图，界面相同                  |

## 迁移策略

1. **第 1 阶段 — 基础设施**：添加 `langchain`、`langgraph`、`langchain-openai` 依赖项。将 `src/llm/client.py` 替换为 `ChatOpenAI` 包装器。保持完全相同的 `chat()` 和 `chat_json()` 方法签名，以便现有代理仍然有效。

2. **阶段 2 — 第一个代理**：将 `FitnessAgent` 转换为 StateGraph。这验证了该模式。所有体能测试必须首先通过。

3. **第 3 阶段 — 剩余代理**：一次转换一个 SummaryAgent、MealAgent、QAAgent。每个转换都是独立的——一个代理不会阻止另一个代理。

4. **阶段 4 — 清理**：删除旧的 `BaseAgent` ABC，添加 `BaseGraphAgent`。添加`registry.py`，淡化`debug.py`中的intent→agent映射。

5. **阶段 5 — 内存和扩展**：连接 `MemorySaver`，然后根据需要添加新代理或模块。

每个阶段都应使 `DEEPSEEK_API_KEY=test uv run pytest -q` 保持绿色。

## 测试

- **节点单元测试**：通过图节点传递模拟LLM，断言状态更改。
- **图集成测试**：使用模拟 ChatModel、`graph.ainvoke()` 编译图，断言最终回复。
- **API 冒烟测试**：带有模拟客户端的 `POST /api/debug/message`，断言响应形状（与当前相同）。
- **CI 中没有真正的 DeepSeek 调用**：在 `ChatOpenAI` 级别进行模拟。
