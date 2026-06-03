# Tool-Calling Butler Agent Design

> 将 Personal Butler Agent 的主对话入口重构为总控 tool-calling agent，让 LLM 自主决定何时调用业务工具，同时保留群聊消息静默收集等确定性保护层。

## Overview

当前系统的主链路是 `IntentRouter.route()` 先分类，再通过 `AgentRegistry.get(intent)` 进入某个领域 agent。这个模式稳定、可测试，但 LLM 不能自主选择工具；新增联网搜索、本地知识检索、多步组合任务时，会不断膨胀意图分类和固定流程。

本设计采用：

1. **总控 ButlerAgent 接管私聊和触发式群聊入口**：LLM 作为决策者，根据用户消息和会话上下文决定是否调用工具。
2. **保留确定性保护层**：群聊非触发消息继续只入库不回复，避免每条群消息都触发 LLM。
3. **复用现有领域 agent 和 service**：第一阶段将 Fitness、Meal、Summary、Knowledge 等能力包装为工具，而不是重写业务逻辑。
4. **Web search 作为普通工具**：模型认为问题需要实时信息时调用联网搜索工具，再基于结果回答。

目标不是一次性删除所有旧结构，而是把主入口从“先分类再分发”迁移到“LLM 调工具完成任务”。`IntentRouter` 在第一阶段保留为兼容模块和回退能力，但不再是 debug/wechat 主入口的默认决策层。

## Scope

### In Scope

- 新增 `src/agents/butler/` 总控 agent 包，使用 LangGraph `StateGraph`、`ToolNode` 和 `tools_condition` 实现 tool-calling 循环。
- 扩展 `LLMClient`，支持绑定工具后返回 LangChain message 对象，而不只返回纯文本。
- 新增工具层，将现有能力包装成 LangChain tools：
  - 记录训练。
  - 生成今日训练建议。
  - 生成饮食计划。
  - 总结文本。
  - 总结群聊历史。
  - 检索本地知识库。
  - 联网搜索。
- 修改 debug 私聊入口：不再先调用 `IntentRouter.route()`，而是调用 `ButlerAgent.handle()`。
- 修改 WeChat Work 回调处理中的触发式消息入口：可回复消息交给 `ButlerAgent.handle()`。
- 保留群聊非触发消息静默入库逻辑。
- 新增搜索配置字段、`.env.example` 示例、配置文档和测试。
- 新增架构决策文档，记录主入口切换为 tool-calling agent 的取舍。
- 保持 `POST /api/debug/message` 响应结构兼容：继续返回 `intent`、`confidence`、`response`、`data`，其中 tool-calling 路径的 `intent` 使用 `butler`。

### Out of Scope

- 删除 `IntentRouter`、`AgentRegistry` 或现有领域 agent。
- 重写 Fitness、Meal、Summary agent 内部图结构。
- 实现浏览器级网页抓取、长网页阅读、网页内容向量化入库。
- 引入外部队列、Redis、Celery 或多进程执行。
- 让群聊每条普通消息都触发 LLM。
- 在测试中调用真实 DeepSeek 或真实搜索 API。

## Core Design

### 1. Entry Flow

私聊 debug 流程从：

```text
POST /api/debug/message
→ IntentRouter.route()
→ AgentRegistry.get(intent)
→ domain_agent.handle()
→ DebugMessageResponse
```

改为：

```text
POST /api/debug/message
→ ButlerAgent.handle()
→ LangGraph agent node 调用 bound LLM
→ LLM 如需工具则产生 tool_calls
→ ToolNode 执行工具
→ 回到 agent node 生成最终回答
→ DebugMessageResponse(intent="butler", confidence=1.0)
```

群聊 debug 和 WeChat Work 回调保留第一层保护：

```text
group message
→ 保存群消息
→ 未命中总结触发词：静默返回
→ 命中触发词：ButlerAgent.handle(extra_state={"chat_type": "group", "chat_id": ...})
```

这样保留当前“群聊消息被动收集、触发词才回复”的产品行为，同时让触发后的处理由 LLM 自主选择工具。

### 2. ButlerAgent Graph

新增文件结构：

```text
src/agents/butler/
├── __init__.py
├── graph.py
├── nodes.py
├── state.py
├── prompts.py
└── tools.py
```

图结构：

```text
START
→ agent
→ tools_condition
   ├── tools → agent
   └── END
```

`agent` 节点负责：

- 组装 system prompt。
- 注入用户消息、最近对话、压缩摘要。
- 调用绑定工具后的 LLM。
- 返回 `messages` 状态。

`tools` 节点使用 LangGraph `ToolNode`。工具执行结果以 `ToolMessage` 形式回到 `messages`，再交给 LLM 生成最终回复或继续调用其他工具。

第一版设置递归限制，防止模型无限调用工具。建议 `recursion_limit=8`，覆盖场景为：一次用户消息最多允许 3 轮工具调用加最终回答。

### 3. State Shape

`ButlerState` 使用 `TypedDict(total=False)`：

```python
class ButlerState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    user_id: str
    chat_type: str
    chat_id: str | None
    conversation_summary: str | None
    recent_messages: list[dict]
    reply: str
    error: str | None
```

`messages` 是 tool-calling 图的核心状态，使用 `add_messages` reducer 累加 HumanMessage、AIMessage、ToolMessage。

`user_id`、`chat_type`、`chat_id` 仍保留在状态中，并通过 LangGraph config 传给工具，工具据此执行数据库查询和权限过滤。

### 4. Tool Catalog

工具命名采用动词短语，描述写清楚何时调用，减少模型误用。

| Tool | 用途 | 内部实现 |
|------|------|----------|
| `log_training` | 用户想记录训练、打卡训练内容 | 调用 `FitnessAgent.handle("log_training", ...)` |
| `get_today_training_plan` | 用户询问今天练什么、训练建议 | 调用 `FitnessAgent.handle("today_plan", ...)` |
| `make_meal_plan` | 用户询问吃什么、食谱、饮食计划 | 调用 `MealAgent.handle("make_meal_plan", ...)` |
| `summarize_text` | 用户要求总结一段明确文本 | 调用 `SummaryAgent.handle("summarize_text", ...)` |
| `summarize_group_chat` | 群聊中用户要求总结最近群聊 | 调用 `SummaryAgent.handle("summarize_group", ...)` |
| `search_local_knowledge` | 用户问题可能被本地知识库回答 | 调用 `KnowledgeService.search()` |
| `search_web` | 用户问题涉及最新、最近、新闻、影视、价格、版本、政策等实时信息 | 调用 `WebSearchService.search()` |

工具返回值统一为简短文本或 JSON 字符串。第一版不让工具直接返回 `AgentResponse` 对象，避免 ToolNode 序列化复杂对象。

### 5. Dependency Injection

ButlerAgent 构造时接收现有单例：

```python
ButlerAgent(
    llm_client=llm_client,
    fitness_agent=fitness_agent,
    meal_agent=meal_agent,
    summary_agent=summary_agent,
    knowledge_service=KnowledgeService(),
    web_search_service=WebSearchService(),
)
```

运行时通过 config 注入：

```python
config = {
    "configurable": {
        "db": db,
        "llm": self._llm,
        "thread_id": f"butler:{user_id}",
        "user_id": user_id,
        "chat_type": chat_type,
        "chat_id": chat_id,
        "tools_context": self._tools_context,
    },
    "recursion_limit": 8,
}
```

工具函数从 `get_config()["configurable"]` 读取数据库会话、用户上下文和领域 agent 引用。这样工具签名只暴露模型需要提供的参数，例如 `message`、`query`、`text`，不让模型填写 `user_id` 或 `chat_id`。

### 6. LLM Client Changes

现有 `LLMClient.chat()` 返回字符串，不能承载 tool calls。新增两个方法：

```python
def bind_tools(self, tools: list) -> Runnable:
    ...

async def ainvoke_messages(self, messages: list, *, tools: list | None = None) -> BaseMessage:
    ...
```

`chat()` 和 `chat_json()` 保持兼容，不影响现有领域 agent。

`ButlerAgent` 使用 `bind_tools()` 后的 runnable 调用模型，得到 `AIMessage`。若模型返回 tool calls，LangGraph 的 `tools_condition` 会路由到 ToolNode。

### 7. Prompt Policy

总控 system prompt 需要清晰约束：

- 你是“小管家”，负责理解用户目标并在需要时调用工具。
- 能直接闲聊就直接回答。
- 涉及用户训练记录、今日训练建议、饮食计划、总结、知识库、实时信息时，优先调用相应工具。
- 涉及最新事实、影视剧、新闻、价格、政策、软件版本等实时信息时，调用 `search_web`。
- 不要编造工具结果；工具没有结果时说明没有查到。
- 工具返回的是事实依据，最终回答要自然、简洁、必要时附来源 URL。
- 不要向用户暴露内部工具名，除非用户询问系统实现。

### 8. Web Search Service

新增 `src/search/`：

```text
src/search/
├── __init__.py
├── schemas.py
└── service.py
```

配置字段：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `WEB_SEARCH_ENABLED` | `false` | 是否启用联网搜索 |
| `WEB_SEARCH_PROVIDER` | `tavily` | 搜索供应商 |
| `WEB_SEARCH_API_KEY` | `""` | 搜索 API key |
| `WEB_SEARCH_MAX_RESULTS` | `5` | 最大结果数 |
| `WEB_SEARCH_TIMEOUT_SECONDS` | `8` | HTTP 超时 |

第一版实现 `tavily` provider。若搜索未配置或关闭，`search_web` 工具返回“联网搜索未启用”，由 LLM 继续给保守回答。

为避免测试依赖真实网络，`WebSearchService` 支持注入 async client 或 provider 函数，并在测试里 mock。

### 9. Backward Compatibility

保留：

- `IntentRouter` 类和测试。
- `AgentRegistry` 类和现有领域 agent 注册。
- `POST /api/debug/message` 路径和响应 schema。
- 群聊非触发消息的 `collect_group` 响应。
- 领域 agent 的 `handle()` 接口。

变化：

- 私聊 debug 响应的 `intent` 从具体意图变为 `butler`。
- 可回复的 WeChat Work 文本/语音消息默认进入 ButlerAgent。
- 工具调用内部可能再使用现有领域 agent，因此单次消息可能触发多次 LLM 调用。

### 10. Error Handling

- ButlerAgent 调用 LLM 失败：返回“LLM 服务暂时不可用，请稍后重试。”
- 工具内部失败：工具返回错误文本，不抛出到图外，最终由 LLM 解释给用户。
- 搜索服务未配置：`search_web` 返回明确的未启用信息。
- 工具调用超过递归限制：捕获异常并返回“这次工具调用太多了，我先停一下，请把需求拆小一点。”
- 领域 agent 返回空回复：工具返回“该工具没有生成有效结果。”

### 11. Testing Strategy

测试不调用真实 DeepSeek 或真实搜索 API。

新增覆盖：

- ButlerAgent 在 fake AIMessage 带 `log_training` tool call 时，会执行训练记录工具。
- ButlerAgent 在 fake AIMessage 带 `search_web` tool call 时，会把搜索结果作为工具消息再生成最终回答。
- debug 私聊入口不再调用 `IntentRouter.route()`。
- 群聊非触发消息仍静默收集，不调用 ButlerAgent。
- 群聊触发消息进入 ButlerAgent，并带上 `chat_type="group"` 和 `chat_id`。
- 搜索关闭时 `search_web` 返回未启用信息。
- LLM tool-calling 失败时 API 返回友好错误。
- 原有领域 agent 测试继续通过。

### 12. Documentation Updates

需要更新：

- `docs/agent/active-context.md`：当前主入口变为 ButlerAgent tool-calling。
- `docs/agent/patterns.md`：新增总控 agent 和 tool 包装模式。
- `docs/agent/decisions.md`：新增 ADR，记录为何主入口迁移为 tool-calling，同时保留确定性保护层。
- `docs/agent/config-variables.md`：新增 web search 配置。
- `docs/agent/troubleshooting.md`：新增 tool-calling 和 web search 排障。
- `.env.example`：新增搜索配置示例。
- `CLAUDE.md` 和 `AGENTS.md`：如根说明提到主流程，需要保持两者字节一致。

## Migration Plan

实现分阶段进行：

1. 增加 LLMClient tool-calling 支持和小型单元测试。
2. 增加 WebSearchService 和配置测试。
3. 增加 ButlerAgent 图和工具层测试。
4. 修改 `src/main.py` wiring，引入 ButlerAgent 单例。
5. 修改 debug route 私聊和群聊触发路径。
6. 修改 WeChat Work callback/message handler 可回复路径。
7. 更新文档和架构决策。
8. 跑全量测试，修复兼容性问题。

每一步都应保持 `DEEPSEEK_API_KEY=test uv run pytest -q` 可恢复为绿色。

## Risks And Trade-Offs

- **模型误选工具**：通过工具描述、system prompt、保留确定性保护层降低风险。
- **成本和延迟增加**：一次用户消息可能先调用工具再总结，必要时后续增加工具结果缓存。
- **DeepSeek tool-calling 兼容性**：当前依赖层支持 `bind_tools()`，DeepSeek 官方支持 tool calls；仍需用真实 key 做一次手动冒烟验证。
- **循环调用工具**：通过 `recursion_limit` 和 prompt 限制工具调用次数。
- **测试复杂度增加**：使用 fake message 和 mock runnable 测试图行为，避免真实 API。

## Acceptance Criteria

- 私聊 `POST /api/debug/message` 通过 ButlerAgent 返回自然语言回复。
- ButlerAgent 能根据 LLM tool calls 执行至少一个业务工具和一个搜索工具。
- 群聊非触发消息仍只保存并静默返回。
- 群聊触发消息进入 ButlerAgent，并可调用群聊总结工具。
- 现有领域 agent 的单元测试继续通过。
- 搜索配置关闭时系统仍可启动，`search_web` 工具给出可理解的降级结果。
- 配置、模式、架构决策和排障文档同步更新。
- 全量测试通过：`DEEPSEEK_API_KEY=test uv run pytest -q`。
