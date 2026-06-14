# Personal Butler Agent — 项目学习指南

> 为初学者编写的完整项目导读，按 10 个维度拆解整个代码库。

---

## 1. 项目用途

**Personal Butler Agent** 是一个企业微信（WeChat Work）智能机器人后端服务。它充当用户的个人 AI 管家，能够：

- **私聊问答**：在私聊场景中提供 15 种工具能力（摘要、知识库 RAG、联网搜索、天气、提醒、翻译、个性化记忆 CRUD 等），支持多轮对话
- **群聊互动**：在群聊 @ 机器人场景中提供受限的群功能（群聊总结、天气、投票、翻译、简单问答）
- **定时推送**：通过 APScheduler 在指定时间向企业微信群 webhook 推送消息（固定正文 + 可选的实时天气追加）
- **私聊提醒**：支持自然语言创建提醒，到期自动通过群 webhook @ 发送者
- **群投票**：支持创建/投票/查看/结束群投票，到期自动推送结果
- **异步深度研究**：私聊提交研究任务后，由独立 Worker 进程生成 LLM 初稿，通过企业微信自建应用主动推送给用户
- **个性化记忆**：从对话中隐式提取用户画像（偏好/事实/习惯/关系），支持记忆的增删改查和语义搜索
- **知识库管理**：支持 Markdown/PDF/网页导入，ChromaDB 向量检索 + SQLite FTS 关键词检索 + LLM 精排

所有入站消息通过**企业微信智能机器人 URL 回调模式**接收，被动回复通过消息体中的 `response_url` 推送。主动推送（定时消息、提醒到期、投票结果、研究报告）通过**企业微信群机器人 webhook** 或**自建应用私聊 API** 独立完成。

---

## 2. 技术栈

| 层次 | 技术 | 用途 |
|------|------|------|
| **Web 框架** | FastAPI | HTTP 服务器，处理企业微信 URL 回调 |
| **Agent 编排** | LangGraph (StateGraph) | Agent 状态机，工具调用循环，多节点路由 |
| **LLM 接口** | langchain-openai (ChatOpenAI) | 统一包装 DeepSeek API，支持工具绑定和流式调用 |
| **异步队列** | Taskiq + Redis Stream | 异步研究任务的生产者-消费者解耦 |
| **ORM** | SQLAlchemy 2.0 (async) | 全异步数据库操作 |
| **数据库** | PostgreSQL (asyncpg, production) / SQLite (aiosqlite, dev fallback) | 结构化数据存储（对话、知识库、提醒、投票、记忆等） |
| **向量数据库** | ChromaDB (嵌入式) | 知识库 chunks 的向量存储和 ANN 检索 |
| **嵌入模型** | DashScope Qwen3-Embedding (1024-dim) | 语义向量生成，带本地哈希 fallback |
| **定时任务** | APScheduler (AsyncIOScheduler) | 群 webhook 定时推送 + 提醒到期扫描 + 投票到期回调 |
>
> **Note**: PostgreSQL is the authoritative production database. SQLite is a local development fallback for zero-dependency setup. All schema changes are managed via Alembic migrations, and production deployments use `DATABASE_REQUIRE_MIGRATIONS=true` to verify migration state. |
| **HTTP 客户端** | httpx | 企业微信 webhook 推送和 response_url 回复 |
| **配置** | pydantic-settings | .env 文件配置加载和类型校验 |
| **数据校验** | Pydantic v2 | 请求/响应模型和数据校验 |
| **包管理** | uv | Python 依赖管理和虚拟环境 |
| **测试** | pytest | 异步测试，mock LLM + 隔离数据库 |
| **语言** | Python 3.13+ | 全异步（async/await） |
| **外部 API** | Open-Meteo (天气)、DuckDuckGo (搜索) | 免费、无需 API Key 的外部数据源 |

---

## 3. 目录结构说明

```
personal_butler_agent/
├── src/                          # 核心源代码
│   ├── main.py                   # FastAPI 应用入口，依赖注入和生命周期管理
│   ├── config.py                 # 配置管理（Settings 类，读取 .env）
│   │
│   ├── agents/                   # Agent 层（场景 agent + 领域 agent）
│   │   ├── private_butler/       # 私聊小管家（ReAct 工具调用循环）
│   │   │   ├── graph.py          # StateGraph 组装 + handle() 入口
│   │   │   ├── state.py          # 状态 TypedDict 定义
│   │   │   ├── nodes.py          # 图节点（call_model, extract_reply 等）
│   │   │   ├── tools.py          # 15 个 LangChain tool 定义
│   │   │   └── prompts.py        # system prompt
│   │   ├── group_mention/        # 群聊 @ 机器人（分类路由 + 受限工具）
│   │   │   ├── graph.py          # StateGraph 组装 + handle() 入口
│   │   │   ├── state.py          # 状态 TypedDict
│   │   │   ├── nodes.py          # 图节点（classify, summarize, poll 等）
│   │   │   ├── tools.py          # 群聊工具（query_weather, add_to_knowledge）
│   │   │   ├── prompts.py        # 各节点 prompt
│   │   │   └── classifier.py     # LLM 兜底分类器
│   │   ├── summary/              # 摘要领域 agent（文本摘要 + 群聊摘要）
│   │   ├── reminder/             # 提醒领域 agent（自然语言解析 + CRUD）
│   │   ├── poll/                 # 群投票领域 agent（创建/投票/结束）
│   │   ├── webhook_composer/     # webhook 内容生成 agent
│   │   ├── memory/               # 个性化记忆（碎片提取 + 画像聚合 + 语义检索）
│   │   │   ├── service.py        # MemoryService 核心服务
│   │   │   ├── extractor.py      # LLM 隐式画像碎片提取器
│   │   │   └── models.py         # ORM 模型（memory_fragments, user_profile）
│   │   └── translate.py          # 翻译共享工具（纯函数，无 agent 类）
│   │
│   ├── messaging/                # 消息层（入站规范化 + 场景分发 + 群策略）
│   │   ├── inbound.py            # InboundMessage 统一消息模型
│   │   ├── dispatch.py           # dispatch_message() 场景分发
│   │   └── group_policy.py       # apply_group_policy() 群消息策略
│   │
│   ├── wechat/                   # 企业微信集成层
│   │   ├── callback_crypto.py    # URL 回调加解密（签名校验 + AES 解密）
│   │   ├── callback_router.py    # FastAPI 路由（GET 验证 + POST 回调）
│   │   ├── callback_handler.py   # 消息处理 + response_url 被动回复
│   │   ├── callback_inbox.py     # 入站消息落库（幂等去重 + 状态追踪）
│   │   └── app_client.py         # 自建应用主动私聊客户端（token 缓存 + ID 转换）
│   │
│   ├── llm/                      # LLM 层
│   │   └── client.py             # LLMClient（ChatOpenAI 包装，chat/chat_json/bind_tools）
│   │
│   ├── knowledge/                # 知识库层
│   │   ├── service.py            # KnowledgeService（ingest + 两阶段检索）
│   │   ├── chroma_store.py       # ChromaDB 嵌入式向量存储
│   │   ├── chunking.py           # 文档分块（段落感知 + overlap）
│   │   ├── embedding.py          # EmbeddingService（DashScope API + 本地哈希 fallback）
│   │   ├── reranker.py           # LLM 重排序（query rewriting + 点对点评分）
│   │   ├── schemas.py            # 知识库 Pydantic 模型
│   │   └── parsers/              # 文档解析器（PDF、网页）
│   │
│   ├── memory/                   # 对话记忆层
│   │   └── conversation.py       # ConversationMemory（滑动窗口 + LLM 压缩摘要）
│   │
│   ├── reminders/                # 提醒生命周期层
│   │   └── service.py            # ReminderService（CRUD + 到期扫描 + 推送）
│   │
│   ├── scheduler/                # 定时调度层
│   │   ├── manager.py            # SchedulerManager（APScheduler 生命周期 + job 注册）
│   │   ├── client.py             # WebhookPushClient（企业微信 webhook HTTP 推送 + errcode 校验）
│   │   ├── config.py             # 目标 JSON 加载和校验
│   │   └── models.py             # WebhookSchedulerTarget 数据模型
│   │
│   ├── research/                 # 异步研究子系统
│   │   ├── service.py            # ResearchTaskService（任务生命周期 CRUD + 幂等）
│   │   ├── broker.py             # Taskiq RedisStreamBroker 实例
│   │   ├── executor.py           # FoundationResearchExecutor（单次 LLM 研究调用）
│   │   ├── delivery.py           # ResearchDeliveryService（身份转换 + 自建应用推送）
│   │   ├── tasks.py              # Taskiq Worker 任务入口（研究 + 投递）
│   │   ├── queue.py              # ResearchDispatcher 协议 + Taskiq 实现
│   │   ├── submission.py         # ResearchSubmissionService（私聊提交门面）
│   │   └── schemas.py            # 研究任务状态和报告 Pydantic 模型
│   │
│   ├── weather/                  # 天气服务层
│   │   ├── service.py            # WeatherService（Open-Meteo geocoding + forecast）
│   │   ├── formatting.py         # 天气报告格式化
│   │   └── schemas.py            # WeatherReport 数据模型
│   │
│   ├── search/                   # 联网搜索层
│   │   ├── service.py            # WebSearchService（DuckDuckGo）
│   │   └── schemas.py            # SearchResult 数据模型
│   │
│   ├── models/                   # SQLAlchemy ORM 模型层
│   │   ├── conversation.py       # ConversationMessage + ConversationSummary
│   │   ├── knowledge.py          # KnowledgeDocument + KnowledgeChunk
│   │   ├── group_message.py      # GroupMessage
│   │   ├── group_webhook.py      # GroupWebhook（chat_id → webhook_url 映射）
│   │   ├── inbound_message.py    # InboundMessage（回调消息幂等记录）
│   │   ├── reminder.py           # Reminder + ReminderRun
│   │   ├── poll.py               # Poll + PollVote
│   │   └── research.py           # ResearchTask + ResearchReport + ResearchDelivery
│   │
│   ├── db/                       # 数据库基础设施
│   │   ├── session.py            # 异步引擎 + session factory + get_db 依赖注入
│   │   └── base.py               # SQLAlchemy DeclarativeBase
│   │
│   ├── graph/                    # 图基础设施
│   │   └── memory.py             # LangGraph MemorySaver 单例（checkpointer）
│   │
│   ├── schemas/                  # 共享数据模式
│   │   └── response.py           # AgentResponse（所有 agent.handle() 返回类型）
│   │
│   └── cli/                      # CLI 入口
│       ├── ingest_knowledge.py   # 知识库导入命令
│       └── migrate_to_chroma.py  # SQLite 向量 → ChromaDB 迁移命令
│
├── tests/                        # 测试代码
├── docs/
│   ├── agent/                    # 项目内存文档（active-context, patterns, decisions 等）
│   └── superpowers/              # 历史设计文档和实现计划
├── config/
│   └── scheduler_targets.example.json  # 定时推送目标配置模板
├── pyproject.toml                # 项目元数据和依赖
├── CLAUDE.md                     # Claude Code 项目指令（与 AGENTS.md 同步）
├── deployment.en.md              # 部署指南
└── .env                          # 本地环境变量（不提交到 git）
```

---

## 4. 核心入口文件

### 4.1 `src/main.py` — 应用主入口

整个应用的装配线。按顺序做了以下事情：

1. **创建单例**（模块级别，进程启动时执行一次）：
   - `LLMClient()` — LLM 客户端
   - `ChromaStore()` — 向量数据库
   - `EmbeddingService()` — 嵌入服务
   - `KnowledgeService()` — 知识库服务
   - `WebSearchService()` — 联网搜索
   - `WeatherService()` — 天气服务
   - `ReminderService()` + `ReminderAgent()` — 提醒
   - `MemoryService()` — 个性化记忆
   - `SummaryAgent()` — 摘要
   - `PollAgent()` — 投票
   - `WebhookComposerAgent()` — webhook 内容生成
   - `PrivateButlerAgent()` — 私聊场景 agent（注入上述所有依赖）
   - `GroupMentionAgent()` — 群聊场景 agent
   - `ResearchTaskService()` — 研究任务管理（条件创建）
   - `ResearchSubmissionService()` — 研究提交门面（`RESEARCH_ENABLED=true` 时才创建）

2. **lifespan 生命周期**（FastAPI async context manager）：
   - `Base.metadata.create_all` — 自动建表
   - 加载 `SCHEDULER_TARGETS_FILE` → 创建 `SchedulerManager` → 启动 APScheduler
   - `ResearchBroker.startup()` — 启动 Taskiq broker（如启用）
   - 关闭时：`broker.shutdown()` + `scheduler.shutdown()` + `engine.dispose()`

3. **注册路由**：
   - 当 `WECOM_AIBOT_TOKEN` + `WECOM_AIBOT_ENCODING_AES_KEY` 已配置时，注册 `GET/POST /api/wechat/aibot/callback`

### 4.2 `src/config.py` — 配置入口

`Settings` 类继承 `pydantic_settings.BaseSettings`，自动从 `.env` 文件加载所有环境变量。包含以下配置组：

- **LLM**：`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`
- **数据库**：`DATABASE_URL`
- **企业微信智能机器人**：`WECOM_AIBOT_TOKEN`, `WECOM_AIBOT_ENCODING_AES_KEY`, `WECOM_AIBOT_BOT_ID`
- **定时推送**：`SCHEDULER_TARGETS_FILE`
- **异步研究**：`RESEARCH_ENABLED`, `REDIS_URL`, `RESEARCH_QUEUE_NAME`
- **自建应用私聊**：`WECOM_APP_CORP_ID`, `WECOM_APP_SECRET`, `WECOM_APP_AGENT_ID`
- **嵌入服务**：`DASHSCOPE_API_KEY`

### 4.3 `src/wechat/callback_router.py` — HTTP 路由入口

唯一的对外 HTTP 接口：

- `GET /api/wechat/aibot/callback` — 企业微信 URL 验证（解密 echostr）
- `POST /api/wechat/aibot/callback` — 接收企业微信推送的消息回调（支持密文 JSON/XML 和明文 JSON）

POST 处理流程：解密 → 提取消息体 → 写入 `inbound_messages` 表 → HTTP 立即返回 200 → FastAPI `BackgroundTasks` 异步处理消息。

---

## 5. 核心模块关系

```
                          ┌─────────────────────────────────────────┐
                          │              src/main.py                │
                          │         (装配所有单例 + 路由)            │
                          └────┬────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
          ▼                    ▼                    ▼
  ┌───────────────┐   ┌───────────────┐   ┌───────────────────┐
  │ wechat/       │   │ agents/       │   │ scheduler/        │
  │ callback      │   │ (场景 agent)  │   │ manager           │
  │ router        │   │               │   │ (APScheduler)     │
  └───┬───────────┘   └───────┬───────┘   └────────┬──────────┘
      │                       │                     │
      ▼                       ▼                     ▼
┌─────────────┐     ┌─────────────────┐    ┌──────────────────┐
│ messaging/  │     │ agents/         │    │ agents/          │
│ inbound     │     │ private_butler  │    │ webhook_composer │
│ dispatch    │     │ group_mention   │    │ reminder         │
│ group_policy│     │ (调用下层)      │    │ poll             │
└─────────────┘     └────────┬────────┘    └──────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
  │ knowledge/    │  │ memory/       │  │ llm/          │
  │ service       │  │ conversation  │  │ client        │
  │ chroma_store  │  │               │  │ (DeepSeek)    │
  │ embedding     │  │               │  │               │
  └───────────────┘  └───────────────┘  └───────────────┘
          │
          ▼
  ┌───────────────┐     ┌───────────────┐     ┌───────────────┐
  │ weather/      │     │ search/       │     │ research/     │
  │ service       │     │ service       │     │ (异步子系统)  │
  │ (Open-Meteo)  │     │ (DuckDuckGo)  │     │               │
  └───────────────┘     └───────────────┘     └───────────────┘
```

**依赖方向**：`main.py` → 场景 agent → 领域 agent/service → LLM/DB/外部 API

场景 agent 之间互不依赖，领域 agent 之间互不依赖。

---

## 6. 请求处理流程

### 6.1 私聊消息完整流程

```
企业微信服务器
  │ POST /api/wechat/aibot/callback (加密 JSON/XML)
  ▼
callback_router.receive_callback()
  │ 1. 解密回调请求体
  │ 2. 提取消息体（校验 aibotid）
  │ 3. record_inbound_message() → 按 msgid 幂等写入 inbound_messages
  │ 4. HTTP 立即返回 {"errcode": 0, "errmsg": "ok"}
  │ 5. BackgroundTasks → process_recorded_message()
  ▼
callback_handler.handle_callback_message()
  │ 1. InboundMessage.from_wecom_callback(msg) → 统一消息结构
  │ 2. dispatch_message() → chat_type="single" → 私聊分支
  ▼
PrivateButlerAgent.handle("private_butler", message, user_id, db)
  │ 1. 检查是否为研究任务提交/查询（正则匹配"深度研究："/"查看研究任务"）
  │ 2. 检查是否为提醒直接意图（绕过 LLM 工具选择）
  │ 3. ConversationMemory.get_context() → 加载多轮对话上下文
  │ 4. MemoryService.get_profiles_grouped() → 加载用户画像
  │ 5. 构造初始 State → graph.ainvoke()
  │
  │ [LangGraph ReAct 循环]
  │   agent 节点（call_model） → LLM 推理 → AIMessage（可能含 tool_calls）
  │   → tools_condition 判断 → 有 tool_calls 进入 ToolNode
  │   → ToolNode 执行工具（搜索/天气/摘要等）→ ToolMessage
  │   → 回到 agent 节点（继续推理或输出回复）
  │   → 无 tool_calls → extract_reply 节点（提取最终回复文本）
  │
  │ 6. ConversationMemory.save_exchange() → 保存对话交换
  │ 7. 旁路异步：_extract_fragments_side_path() → 提取用户画像碎片
  ▼
AgentResponse(reply="...")
  │
  ▼
reply_client.send_reply(response_url, content)
  │ POST markdown 到企业微信 response_url
  ▼
用户在私聊中看到回复
```

### 6.2 群聊消息完整流程

```
企业微信服务器（群聊中用户 @ 了机器人）
  │ POST /api/wechat/aibot/callback
  ▼
... 同上走到 dispatch_message()
  │ chat_type="group"
  ▼
apply_group_policy(message, db)
  │ 1. 检查 content 非空、chat_id 非空
  │ 2. GroupMessage.save() → 保存群消息
  │ 3. GroupMessage.cleanup() → 保留最近 200 条
  │ 4. classify_group_trigger() → 关键词匹配触发类别
  │    - 总结关键词 → "summarize_group"
  │    - 天气关键词 → "weather"
  │    - 投票关键词 → "poll_create"/"poll_vote"/"poll_view"/"poll_end"
  │    - 翻译关键词 → "translate"
  │    - 疑问标记 → "simple_qa"
  │    - 未匹配 → 检查是否为投票动作 → 都不是 → 不回复
  │ 5. 如果是 trigger → GroupPolicyDecision(should_reply=True, category=...)
  ▼
GroupMentionAgent.handle("group_mention", message, user_id, db, extra_state)
  │ 1. dispatch_message() 注入 group_category → agent 不再重复分类
  │ 2. graph.ainvoke()
  │
  │ [LangGraph 分类路由]
  │   classify_node → route_by_category 条件边
  │   → summarize_group / weather(agent+ToolNode) / simple_qa /
  │     poll / translate / unsupported
  │
  ▼
AgentResponse(reply="...")
  │
  ▼
reply_client.send_reply(response_url, content)
  │
  ▼
群成员在群聊中看到机器人回复
```

---

## 7. Agent 工作流程

### 7.1 Agent 统一模式

所有 agent 遵循统一接口：

```
agents/<name>/
├── __init__.py    # 只做 re-export
├── state.py       # TypedDict(total=False) 定义状态字段
├── nodes.py       # 异步函数 (state: dict) -> dict 返回增量状态
├── graph.py       # StateGraph 组装 + Agent 类 + handle() 入口
└── prompts.py     # system/user prompt 字符串（可选）
```

**Agent 类**包含：
- `__init__()`：注入依赖，编译 LangGraph
- `_build_graph()`：组装 StateGraph（add_node + add_edge + conditional_edges → compile）
- `handle(intent, message, user_id, db, extra_state=None) -> AgentResponse`：对外统一入口

### 7.2 PrivateButlerAgent（私聊）

**图结构**（ReAct 模式）：

```
START → agent (call_model) → tools_condition
                              ├─ tool_calls → tools (ToolNode) → agent (循环)
                              └─ no tool_calls → extract_reply → END
```

**15 个工具**：`summarize_text`, `summarize_group_chat`, `search_local_knowledge`, `add_to_knowledge`, `search_web`, `query_weather`, `create_group_webhook_reminder`, `list_reminders`, `cancel_reminder`, `translate`, `add_memory`, `list_memories`, `update_memory`, `delete_memory`, `search_memory`

**关键设计**：
- 工具从 `langgraph.config.get_config()` 读取运行时上下文（db, user_id, chat_type, chat_id），而非从 LLM 参数获取 — 防止模型幻觉注入敏感上下文
- 提醒请求通过正则预匹配直接调用 `ReminderAgent.handle()`，绕过 LLM 工具选择，降低延迟
- 研究任务提交/查询通过正则拦截（"深度研究："、"查看研究任务 R..."），不进入 LLM
- 旁路记忆提取用 `asyncio.create_task()` 异步执行，不阻塞主回复

### 7.3 GroupMentionAgent（群聊）

**图结构**（分类路由模式）：

```
START → classify → route_by_category
                    ├─ summarize_group → END
                    ├─ weather → agent → tools_condition
                    │               ├─ tool_calls → tools → agent
                    │               └─ END → extract_tool_reply → END
                    ├─ simple_qa → END
                    ├─ poll → END
                    ├─ translate → END
                    └─ unsupported → END
```

**限制**：群聊只有 `query_weather` 和 `add_to_knowledge` 两个可选工具。群聊总结、投票、翻译都是独立的图节点（单次 LLM 调用），不进入工具循环。

### 7.4 领域 Agent

| Agent | 图结构 | 用途 |
|-------|--------|------|
| `SummaryAgent` | 线性（单节点） | 文本摘要 + 群聊摘要 |
| `ReminderAgent` | 线性（单节点） | 自然语言解析创建提醒 + CRUD |
| `PollAgent` | 条件路由 | 创建/投票/查看/结束投票 |
| `WebhookComposerAgent` | ReAct（小工具循环） | 为定时推送生成 markdown 正文 |

### 7.5 共享工具模式

`src/agents/translate.py` 是纯函数（不是 agent 类），被 `PrivateButlerAgent`（作为 LangChain tool）和 `GroupMentionAgent`（作为图节点）共享调用。适用于不需要状态、持久化和多步路由的单次 LLM 调用。

---

## 8. 数据流

### 8.1 存储架构（ADR-002）

```
┌──────────────────────────────────────────────────┐
│                  SQLite (butler.db)               │
│                                                   │
│  ┌─────────────┐  ┌──────────────┐               │
│  │ conversation│  │ knowledge    │               │
│  │ _messages   │  │ _documents   │               │
│  │ _summaries  │  │ _chunks      │               │
│  └─────────────┘  └──────────────┘               │
│  ┌─────────────┐  ┌──────────────┐               │
│  │ reminders   │  │ polls        │               │
│  │ _runs       │  │ _votes       │               │
│  └─────────────┘  └──────────────┘               │
│  ┌─────────────┐  ┌──────────────┐               │
│  │ group_      │  │ group_       │               │
│  │ messages    │  │ webhooks     │               │
│  └─────────────┘  └──────────────┘               │
│  ┌─────────────┐  ┌──────────────┐               │
│  │ research_   │  │ memory_      │               │
│  │ tasks/      │  │ fragments    │               │
│  │ reports/    │  │ user_profile │               │
│  │ deliveries  │  │              │               │
│  └─────────────┘  └──────────────┘               │
│  ┌─────────────┐                                 │
│  │ inbound_    │                                 │
│  │ messages    │                                 │
│  └─────────────┘                                 │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│              ChromaDB (chroma_data/)              │
│         知识库 chunks 的向量嵌入索引               │
│         支持 ANN 检索 + metadata 过滤              │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│           Redis Stream (仅 RESEARCH_ENABLED)       │
│     butler-research: 研究任务队列                  │
│     Taskiq producer → Redis Stream → Worker       │
└──────────────────────────────────────────────────┘
```

### 8.2 对话记忆数据流

```
用户发送消息
  │
  ▼
ConversationMemory.get_context(user_id, db)
  │ 1. 从 conversation_summaries 读取压缩摘要
  │ 2. 从 conversation_messages 读取最近 12 条
  │ 返回 (summary, recent_messages)
  ▼
注入到 agent State（conversation_summary + recent_messages）
  │
  ▼
agent 生成回复后
  │
  ▼
ConversationMemory.save_exchange(user_id, user_msg, reply, db)
  │ 1. 写入 2 条新消息（user + assistant）
  │ 2. 检查总消息数 > 24 → 触发压缩
  │    _maybe_compress():
  │      取最早 12 条 → 拼上已有摘要 → LLM 生成新摘要
  │      → upsert conversation_summaries → 删除已压缩的 12 条消息
```

### 8.3 个性化记忆数据流

```
用户发送私聊消息
  │
  ▼
PrivateButlerAgent.handle()
  │ 1. get_profiles_grouped() → 加载已确认的用户画像
  │ 2. 注入 profile_context 到 LLM system prompt
  │ 3. graph.ainvoke() → 生成回复
  │ 4. save_exchange() → 保存对话
  │ 5. asyncio.create_task(_extract_fragments_side_path())
  │
  └── [旁路异步，不阻塞回复]
        │
        ▼
      _extract_fragments_side_path()
        │ 1. get_profiles_grouped() → 加载已有画像（独立 DB session）
        │ 2. extract_fragments() → LLM 从消息中提取碎片
        │    (preference/fact/habit/relationship + signal_strength)
        │ 3. add_fragment() → 写入 memory_fragments 表
        │ 4. detect_contradiction() → 矛盾检测
        │ 5. aggregate_fragments() → 同类型碎片出现 ≥ 3 次 → 升级为 user_profile
```

### 8.4 知识库检索数据流（两阶段 RAG）

```
用户问题: "如何配置定时推送？"
  │
  ▼
KnowledgeService.search(query, user_id, db, llm=...)
  │
  │ [Phase 1: 粗筛]
  ├─ ChromaStore.query() → 向量 ANN 检索 (top 20)
  ├─ SQLite FTS → 关键词全文检索 (top 20)
  └─ 合并去重 (按 chunk_id)
  │
  │ [Phase 2: 精排]（仅当 llm 参数传入时）
  ├─ query_rewrite() → LLM 改写查询
  └─ rerank_chunks() → LLM 逐条评分 (0-10)
  │
  ▼
返回排序后的 KnowledgeChunkResult 列表
```

### 8.5 异步研究数据流

```
用户在私聊发送: "深度研究：Python asyncio 最佳实践"
  │
  ▼
PrivateButlerAgent.handle() → 正则匹配"深度研究："
  │
  ▼
ResearchSubmissionService.submit()
  │ 1. ResearchTaskService.create_task()
  │    - 按 source_msgid 幂等去重
  │    - 检查用户是否有 active 任务（一用户一任务）
  │    - INSERT research_tasks (status=queued)
  │    - INSERT research_deliveries (status=pending)
  │ 2. dispatcher.enqueue_research(task_id)
  │    → Taskiq: run_research_task.kiq(task_id)
  │    → Redis Stream: butler-research
  │
  │ [HTTP 请求结束，用户收到 "研究任务已提交" 回复]
  │
  ▼
Worker 进程 (taskiq worker)
  │
  ▼
run_research_task(task_id)  [Taskiq task]
  │ 1. 从 Redis Stream 拉取 task_id
  │ 2. ResearchTaskService.mark_running(task_id)
  │ 3. FoundationResearchExecutor.execute()
  │    - 从 DB 加载任务
  │    - 构造研究 prompt
  │    - LLM 单次调用生成研究初稿
  │    - ResearchTaskService.complete_with_report()
  │      → INSERT research_reports (quality_status="unreviewed_foundation")
  │      → UPDATE research_tasks (status=completed)
  │ 4. dispatcher.enqueue_delivery(task_id)
  │    → Taskiq: deliver_research_task.kiq(task_id)
  │
  ▼
deliver_research_task(task_id)  [独立 Taskiq task]
  │ 1. ResearchDeliveryService.deliver()
  │ 2. 从 DB 加载报告
  │ 3. WeComAppMessageClient.send_text()
  │    - RedisAccessTokenCache → 获取/缓存 access_token
  │    - open_userid → userid 转换 (查 WeComUserBinding)
  │    - 调用企业微信自建应用 API 发送私聊消息
  │ 4. UPDATE research_deliveries (status=sent)
  │
  ▼
用户在企业微信中收到研究报告私聊推送
```

---

## 9. 配置文件说明

### 9.1 `.env` 文件（主配置）

由 `src/config.py` 的 `Settings` 类加载，所有变量说明见 `docs/agent/config-variables.md`。

**最小可运行配置**（仅私聊功能）：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxx
```

**完整智能机器人配置**（接入企业微信）：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite+aiosqlite:///butler.db

WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WECOM_AIBOT_TOKEN=your-callback-token
WECOM_AIBOT_ENCODING_AES_KEY=your-43-char-encoding-aes-key
```

**启用定时推送**：添加 `SCHEDULER_TARGETS_FILE=config/scheduler_targets.local.json`

**启用异步研究**：添加 `RESEARCH_ENABLED=true` + Redis 配置 + 自建应用配置

**启用语义嵌入**：添加 `DASHSCOPE_API_KEY=sk-xxxxxxxx`

### 9.2 `config/scheduler_targets.local.json`（定时推送目标）

```json
[
  {
    "name": "my-group-morning",           // 内部标识（稳定，用于 job ID）
    "display_name": "我的工作群",          // 用户可见名称
    "cron": "0 9 * * *",                  // cron 表达式
    "webhook_url": "https://qyapi.weixin.qq.com/...",
    "mode": "raw",                         // "raw"=固定正文, "compose"=LLM 生成
    "message": "早上好，今天重点关注：...",
    "weather_query": "今天杭州天气",        // 仅 raw 模式，可选
    "aliases": ["我的工作群"],             // 用户私聊中使用的群名别名
    "enabled": true
  }
]
```

### 9.3 `pyproject.toml`（项目依赖）

关键的 CLI 入口点：
- `butler-ingest-knowledge` → 知识库导入
- `butler-migrate-to-chroma` → SQLite 向量迁移到 ChromaDB

---

## 10. 初学者阅读顺序（推荐）

按以下顺序阅读代码，每层理解后再进入下一层：

### 第一层：基础设施（理解项目骨架）

| 顺序 | 文件 | 重点关注 |
|------|------|----------|
| 1 | `src/config.py` | Settings 类有哪些配置项，各自用途 |
| 2 | `src/db/session.py` | engine 创建、async_session factory、get_db 依赖注入 |
| 3 | `src/db/base.py` | DeclarativeBase（极其简单） |
| 4 | `src/llm/client.py` | LLMClient：chat/chat_json/bind_tools/ainvoke_messages |
| 5 | `src/schemas/response.py` | AgentResponse 是所有 agent 的统一返回类型 |

### 第二层：消息流（理解入站 → 分发 → agent）

| 顺序 | 文件 | 重点关注 |
|------|------|----------|
| 6 | `src/messaging/inbound.py` | InboundMessage 如何从企微回调消息体提取字段 |
| 7 | `src/messaging/group_policy.py` | classify_group_trigger() 关键词匹配逻辑 |
| 8 | `src/messaging/dispatch.py` | dispatch_message() 如何按 chat_type 分发 |
| 9 | `src/wechat/callback_handler.py` | handle_callback_message() 串联规范化 → 分发 → 回复 |

### 第三层：企微集成（理解加密和路由）

| 顺序 | 文件 | 重点关注 |
|------|------|----------|
| 10 | `src/wechat/callback_crypto.py` | 签名校验 + AES 解密 |
| 11 | `src/wechat/callback_inbox.py` | 入站消息幂等落库 + 状态追踪 |
| 12 | `src/wechat/callback_router.py` | FastAPI 路由：GET 验证 + POST 回调 + BackgroundTasks |

### 第四层：主入口（理解装配全景）

| 顺序 | 文件 | 重点关注 |
|------|------|----------|
| 13 | `src/main.py` | 单例创建顺序、lifespan 生命周期、条件路由注册 |

### 第五层：私聊 Agent（理解 ReAct 工具调用）

| 顺序 | 文件 | 重点关注 |
|------|------|----------|
| 14 | `src/agents/private_butler/state.py` | PrivateButlerState 有哪些字段 |
| 15 | `src/agents/private_butler/tools.py` | 15 个工具的签名和 _runtime() 上下文读取 |
| 16 | `src/agents/private_butler/nodes.py` | call_model 和 extract_reply 节点 |
| 17 | `src/agents/private_butler/prompts.py` | system prompt（含 profile_context 占位符） |
| 18 | `src/agents/private_butler/graph.py` | 图组装 + handle() 完整流程（研究/提醒拦截、记忆注入、旁路提取） |

### 第六层：群聊 Agent（理解分类路由）

| 顺序 | 文件 | 重点关注 |
|------|------|----------|
| 19 | `src/agents/group_mention/state.py` | GroupMentionState |
| 20 | `src/agents/group_mention/nodes.py` | 各分类节点的实现 |
| 21 | `src/agents/group_mention/tools.py` | 群聊受限工具 |
| 22 | `src/agents/group_mention/graph.py` | 图组装 + handle() + 条件路由 |

### 第七层：领域服务和数据层

| 顺序 | 文件 | 重点关注 |
|------|------|----------|
| 23 | `src/memory/conversation.py` | ConversationMemory：get_context → save_exchange → _maybe_compress |
| 24 | `src/knowledge/service.py` | KnowledgeService：ingest() 和 search() 两阶段检索 |
| 25 | `src/knowledge/chroma_store.py` | ChromaDB 封装 |
| 26 | `src/knowledge/embedding.py` | 语义嵌入 + 本地哈希 fallback |
| 27 | `src/weather/service.py` | Open-Meteo geocoding + forecast |
| 28 | `src/reminders/service.py` | 提醒 CRUD + 到期扫描 |
| 29 | `src/scheduler/manager.py` | APScheduler 生命周期 + cron job + 提醒扫描 |

### 第八层：高级特性

| 顺序 | 文件 | 重点关注 |
|------|------|----------|
| 30 | `src/agents/memory/service.py` | MemoryService：碎片管理 + 聚合升级 + 重要性计算 |
| 31 | `src/agents/memory/extractor.py` | LLM 隐式画像提取 |
| 32 | `src/research/service.py` | 研究任务生命周期 CRUD + 幂等 |
| 33 | `src/research/tasks.py` | Taskiq 研究/投递 Worker 入口 |
| 34 | `src/research/executor.py` | 研究执行器（单次 LLM 调用） |
| 35 | `src/research/delivery.py` | 投递服务（身份转换 + 自建应用推送） |
| 36 | `src/agents/poll/graph.py` | 投票完整生命周期 |
| 37 | `src/agents/webhook_composer/graph.py` | 定时推送内容生成 |

### 第九层：文档

| 文件 | 用途 |
|------|------|
| `docs/agent/active-context.md` | 当前项目状态和已实现功能总览 |
| `docs/agent/patterns.md` | 所有已建立的代码模式 |
| `docs/agent/decisions.md` | 25 个架构决策（ADR）及理由 |
| `docs/agent/config-variables.md` | 环境变量完整指南 |
| `docs/agent/troubleshooting.md` | 已知故障排查手册 |
| `deployment.en.md` | 部署指南 |

---

## 关键设计原则速览

1. **场景优先分发**：先判断私聊/群聊/定时推送，再决定 agent 行为，而非全局意图分类
2. **确定性守卫在外，LLM 在里**：群消息关键词分类、提醒/研究正则拦截、群策略判断都在 LLM 之前执行
3. **DB 是权威数据源**：所有状态存在 SQLite，队列只传 task_id，Worker 自行重新打开 session
4. **隔离投递**：研究执行失败不回滚已生成的报告；投递失败不回滚研究结果
5. **工具读取运行时上下文**：从 `langgraph.config.get_config()` 获取 db/user/chat，而非信任 LLM 提供的参数
6. **旁路异步不阻塞**：记忆提取用 `create_task`，回复先生成后提取
7. **降级不宕机**：嵌入 API 失败 → 本地哈希；天气 API 失败 → 提示文本；研究 Redis 不可用 → 功能关闭
