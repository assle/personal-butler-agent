# Personal Butler Agent

[English](README.en.md)

基于企业微信的 AI 私人管家系统 —— 通过自然语言交互管理健身、饮食、群聊总结等日常事务。

## 架构概览

```
用户 → 企业微信智能机器人 URL 回调 → FastAPI 回调接口 → Intent Router (规则 + LLM)
                                                                     ↓
                                                  Agent Registry
                                                         ↓
                                         ┌───────┬───────┼───────┬────────┐
                                         ↓       ↓       ↓       ↓        ↓
                                      Fitness Summary  Meal     QA    (可扩展)
                                         ↓       ↓       ↓       ↓
                                         └───────┴───────┴───────┘
                                                   │
                                             StateGraph 引擎
                                          (LangGraph + MemorySaver)
                                                   │
                                               SQLite 数据库
                                                   │
                                                   ↓
                                             智能机器人回调
                                            (response_url 回复)
                                         ↓
                                   企业微信用户/群聊
```

**七层设计：**

| 层 | 技术 | 说明 |
|----|------|------|
| 智能机器人 | 企业微信 URL 回调 | 交互入口，支持私聊、群聊 @、入站落库、后台处理和 response_url 回复 |
| Agent 编排 | LangGraph StateGraph | 状态机驱动，多步推理，条件路由 |
| LLM | LangChain ChatOpenAI → DeepSeek | 意图理解、内容生成、结构化提取 |
| 规则模块 | 关键词匹配 | 确定性路由，零成本 |
| 记忆层 | SQLite + MemorySaver | 持久化偏好/训练记录 + 多轮对话 checkpoint |
| 调度器 | APScheduler | 定时任务驱动（日报、提醒） |

## 技术栈

| 组件 | 选型 |
|------|------|
| Runtime | Python 3.13+ |
| Web 框架 | FastAPI |
| Agent 框架 | LangGraph + LangChain |
| LLM | langchain-openai → DeepSeek API |
| 企业微信加解密 | cryptography (AES-256-CBC) |
| ORM | SQLAlchemy 2.0 (async) + aiosqlite |
| 数据校验 | Pydantic v2 |
| 定时任务 | APScheduler |
| 包管理 | uv |
| 测试 | pytest + pytest-asyncio |

## 项目结构

```
personal_butler_agent/
├── src/
│   ├── main.py              # FastAPI 应用入口 + AgentRegistry 注册 + 条件注册企业微信 URL 回调
│   ├── config.py            # .env 配置加载（LLM / DB / 企业微信）
│   ├── router/
│   │   └── debug.py         # POST /api/debug/message（本地调试端点）
│   ├── wechat/              # 企业微信集成模块
│   │   ├── callback_crypto.py  # 智能机器人 URL 回调 AES 解密 + SHA1 签名验证
│   │   ├── callback_router.py  # GET/POST /api/wechat/aibot/callback
│   │   ├── callback_inbox.py   # 入站消息 msgid 幂等落库
│   │   ├── callback_handler.py # 意图路由 → agent → response_url 回复
│   │   └── ws_client.py        # 旧 WebSocket 长连接兼容模块（main.py 不启动）
│   ├── scheduler/           # APScheduler 定时推送模块（URL 回调模式暂不启动）
│   ├── intent/
│   │   ├── rules.py         # 关键词规则匹配
│   │   └── router.py        # 规则优先 + LLM 兜底路由
│   ├── agents/
│   │   ├── registry.py      # intent → agent 中心注册表
│   │   ├── base.py          # BaseGraphAgent 抽象基类
│   │   ├── fitness/
│   │   │   ├── state.py     # FitnessState TypedDict
│   │   │   ├── nodes.py     # 节点函数（extract/validate/persist/generate...）
│   │   │   └── graph.py     # StateGraph 组装 + FitnessAgent 类
│   │   ├── summary/         # 同上 pattern
│   │   ├── meal/            # 同上 pattern
│   │   └── qa/              # 同上 pattern
│   ├── graph/
│   │   └── memory.py        # LangGraph MemorySaver 共享实例
│   ├── memory/
│   │   ├── __init__.py
│   │   └── conversation.py  # ConversationMemory 对话记忆管理
│   ├── models/
│   │   ├── training.py      # 训练记录 ORM
│   │   ├── preference.py    # 用户偏好 ORM (JSON)
│   │   ├── group_message.py # 群聊消息 ORM（收集 + 触发总结）
│   │   └── conversation.py  # 对话记忆 ORM（消息 + 摘要压缩）
│   ├── schemas/
│   │   ├── request.py       # 请求 Schema
│   │   └── response.py      # 响应 Schema
│   ├── llm/
│   │   └── client.py        # ChatOpenAI 封装（DeepSeek 兼容）
│   ├── knowledge/           # Stage 1 SQLite 知识库检索
│   └── db/
│       ├── base.py          # SQLAlchemy DeclarativeBase
│       └── session.py       # 异步引擎 + 会话工厂 + get_db 依赖注入
├── tests/                   # pytest 测试
├── docs/
│   ├── agent/               # 项目记忆文档（active-context / patterns / decisions / upgrade-roadmap）
│   └── superpowers/
│       ├── specs/           # 设计文档
│       └── plans/           # 实现计划
├── pyproject.toml
├── .env.example
├── CLAUDE.md                # AI 助手项目指令
├── 部署指南.md               # Dev / Production 环境部署完整步骤
└── README.md
```

## 快速开始

### Dev 环境（本地）

```bash
# 1. 克隆项目
git clone https://github.com/assle/personal-butler-agent.git
cd personal-butler-agent

# 2. 安装依赖
uv sync
uv pip install pytest pytest-asyncio httpx

# 3. 配置 .env
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-xxxxxxxx

# 4. 启动开发服务器
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000

# 5. 测试调用
curl -X POST http://localhost:8000/api/debug/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"assle","message":"打卡 今天练胸 卧推80kg5组8次"}'
```

### Production 环境（云服务器）

详见 [`部署指南.md`](部署指南.md) —— 包含 uv + Caddy + systemd 从零到上线的完整步骤。

## API 端点

### POST /api/debug/message

本地调试端点，模拟企业微信消息回调。始终可用，无需企业微信配置。

**请求：**

```json
{
  "user_id": "assle",
  "message": "打卡 今天练胸 卧推80kg5组8次",
  "timestamp": "2026-05-29T16:30:00"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | 是 | 用户标识 |
| message | string | 是 | 消息文本 |
| timestamp | datetime | 否 | 消息时间 |

**响应：**

```json
{
  "intent": "log_training",
  "confidence": 1.0,
  "response": "已记录 2 条训练：卧推、飞鸟",
  "data": { "records": [{ "muscle_group": "胸", "exercise": "卧推", ... }] }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| intent | string | 识别的意图 |
| confidence | float | 置信度 0.0-1.0 |
| response | string | 回复文本 |
| data | object | 结构化数据（可选） |

### 企业微信智能机器人 URL 回调

智能机器人通过 URL 回调接入。**当 `.env` 中 `WECOM_AIBOT_TOKEN` 和 `WECOM_AIBOT_ENCODING_AES_KEY` 均配置时，应用注册 `/api/wechat/aibot/callback`。**

| 能力 | 说明 |
|------|------|
| 消息接收 | 企业微信 POST 到 `/api/wechat/aibot/callback` |
| 入站可靠性 | 按 `msgid` 写入 `inbound_messages`，重复回调幂等去重 |
| 被动回复 | agent 处理完成后通过消息体里的 `response_url` 发送 markdown 回复 |
| 主动推送 | URL 回调模式暂不启动 WebSocket，因此 APScheduler 主动推送暂不可用 |

后台配置 URL：

```text
https://<你的域名>/api/wechat/aibot/callback
```

与旧 WebSocket 长连接的关键区别：
- 连接方式为 HTTPS URL 回调，需要公网域名、Token 和 EncodingAESKey
- 应用收到消息后先落库再后台处理，减少断线窗口导致的入站丢失
- 回复走临时 `response_url`，不再通过 `aibot_respond_msg` 长连接回复

### 消息类型支持

| 消息类型 | 智能机器人 | 说明 |
|----------|------------|------|
| 文本 | 支持 | 意图路由 → agent 回复 |
| 语音 | 支持 | 提取企业微信内置识别文本后当文本路由；识别为空时静默忽略 |
| 其他 | 暂不支持 | 回复"暂不支持该消息类型" |

## 支持的意图

| 意图 | 触发方式 | 功能 |
|------|----------|------|
| `log_training` | "打卡 练胸..." / "记录训练" | 自然语言记录训练数据 |
| `today_plan` | "今天练什么" / "训练建议" | 基于历史和偏好生成训练计划 |
| `summarize_text` | "帮我总结..." / "summary" | 结构化文本摘要（用户提供内容） |
| `summarize_group` | 群聊中"总结"/"摘要"/"概括"/"汇总" | 拉取群聊历史生成结构化摘要 |
| `make_meal_plan` | "今天吃什么" / "食谱" | 生成带营养估算的一日三餐 |
| `qa` | 默认兜底 | 个性化问答 |
| `unknown` | 无法识别时 | 返回提示 |

**意图路由策略：** 关键词规则优先（确定性、零成本），未命中时由 LangChain ChatOpenAI 调用 DeepSeek 兜底分类。

## Agent 架构

每个 Agent 是一个 LangGraph `StateGraph`，由三部分组成：

| 文件 | 职责 |
|------|------|
| `state.py` | 定义 graph 状态的 TypedDict |
| `nodes.py` | 单职责异步节点函数（extract / validate / generate / format 等） |
| `graph.py` | StateGraph 组装 + Agent 类（提供 `handle()` 入口） |

**FitnessAgent 示例：**

```
__start__
    │
[path_condition] ← 根据 intent 条件路由
 /               \
log_training     today_plan
 extract         fetch_history
 validate        fetch_prefs
 persist         generate
 format_log      format_plan
    \               /
   __end__        __end__
```

添加新 Agent：创建 `state.py` + `nodes.py` + `graph.py` → 在 `src/main.py` 中 `agent_registry.register(intent, agent)` 注册。

## 企业微信集成

### 智能机器人 URL 回调

- 用户在企业微信中给智能机器人发私聊或在群里 @机器人 → 企业微信 POST 到 `/api/wechat/aibot/callback`
- 应用先按 `msgid` 写入 `inbound_messages`，重复回调不重复处理
- 应用在后台 task 中完成意图路由和 agent 处理，避免 LLM 调用阻塞 HTTP 成功响应
- 回复方式：通过消息体中的临时 `response_url` 下发 markdown 消息
- 主动推送：URL 回调模式暂不启动 WebSocket，APScheduler 主动推送暂不可用

### 配置变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `WECOM_AIBOT_BOT_ID` | 智能机器人必需 | 智能机器人 BotID，用于消息体 `aibotid` 校验 |
| `WECOM_AIBOT_TOKEN` | 智能机器人必需 | URL 回调 Token |
| `WECOM_AIBOT_ENCODING_AES_KEY` | 智能机器人必需 | URL 回调 EncodingAESKey |
| `SCHEDULER_CRON` | 定时推送可选 | cron 表达式，例如 `0 9 * * 1-5` |
| `SCHEDULER_TARGET_TYPE` | 定时推送可选 | 推送目标类型：`single` 或 `group` |
| `SCHEDULER_TARGET_ID` | 定时推送可选 | 单聊 userid 或群聊 chatid |
| `SCHEDULER_MESSAGE` | 定时推送可选 | 定时触发时交给 agent 的消息 |
| `SCHEDULER_INTENT` | 定时推送可选 | 可选 intent，留空时自动路由 |

## 数据库

使用 SQLite 本地文件存储，四张核心表：

**training_records** — 训练记录

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| user_id | TEXT NOT NULL | 用户标识 |
| date | TEXT NOT NULL | 训练日期 YYYY-MM-DD |
| muscle_group | TEXT NOT NULL | 训练部位 |
| exercise | TEXT NOT NULL | 动作名称 |
| sets | INTEGER NOT NULL | 组数 |
| reps | INTEGER NOT NULL | 次数 |
| weight_kg | REAL | 重量 |
| created_at | TEXT | 创建时间 |

**user_preferences** — 用户偏好

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| user_id | TEXT NOT NULL UNIQUE | 用户标识 |
| preferences | TEXT NOT NULL | JSON 偏好（按 namespace 组织） |

**group_messages** — 群聊消息收集

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| chat_id | TEXT NOT NULL | 群聊 ID |
| user_id | TEXT NOT NULL | 发送者 |
| content | TEXT NOT NULL | 消息内容 |
| timestamp | INTEGER NOT NULL | 消息时间戳 |
| created_at | TEXT | 创建时间 |

每个群最多保留 200 条消息，超出自动清理。

**conversation_messages** — 对话消息

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| user_id | TEXT NOT NULL | 用户标识 |
| role | TEXT NOT NULL | 消息角色（user / assistant） |
| content | TEXT NOT NULL | 消息文本 |
| created_at | TEXT NOT NULL | ISO 时间戳 |

**conversation_summaries** — 对话压缩摘要

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| user_id | TEXT NOT NULL UNIQUE | 用户标识 |
| summary_text | TEXT NOT NULL | LLM 压缩的摘要文本 |
| last_summarized_at | TEXT NOT NULL | 最后压缩时间 |

每条用户消息超过 24 条时，自动将最早 12 条压缩为一句摘要，保留最近 12 条在表中。

preferences JSON 结构可扩展，新模块只需添加自己的 namespace：

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

## 运行测试

```bash
# 运行全部测试（118 个）
DEEPSEEK_API_KEY=test uv run pytest -q

# 运行单个模块
DEEPSEEK_API_KEY=test uv run pytest tests/test_fitness.py -v

# 运行智能机器人回调模块测试
DEEPSEEK_API_KEY=test uv run pytest tests/test_aibot_callback.py -v
```

## 已实现功能

以下功能已完整实现端到端工作流，从用户输入到应用回复全过程无错误且返回正确结果。

---

### 1. 智能机器人私聊问答

用户在企业微信中向智能机器人发送消息，应用经过「URL 回调 → 入站落库 → 意图识别 → LLM 处理 → response_url 回复」链路，返回 AI 生成的回答。

**使用方式：**

1. 在企业微信管理后台创建智能机器人，配置回调 URL 为 `https://<你的域名>/api/wechat/aibot/callback`
2. 在 `.env` 中填入智能机器人配置：
   ```bash
   WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   WECOM_AIBOT_TOKEN=your-callback-token
   WECOM_AIBOT_ENCODING_AES_KEY=your-43-char-encoding-aes-key
   ```
3. 重启服务，在企业微信中找到该智能机器人，发送消息即可

**已接入的五种意图及调用示例：**

#### 1.1 训练打卡 (`log_training`)

记录健身训练数据，支持自然语言描述多种动作、重量、组数和次数。

| 触发方式 | 示例消息 |
|----------|----------|
| 包含 "打卡" 关键词 | `打卡 今天练胸 卧推80kg5组8次 飞鸟15kg4组12次` |
| 包含 "记录训练" | `记录训练 深蹲100kg5x5 腿举200kg3x10` |

**收到回复：** 应用解析训练数据后存入 SQLite，回复已记录的动作列表和结构化摘要，例如：

> 已记录 2 条训练：卧推 80kg 5组8次、飞鸟 15kg 4组12次

同时数据持久化到 `training_records` 表中，包含动作名称、重量、组数、次数、训练日期等信息。

#### 1.2 训练计划建议 (`today_plan`)

基于历史训练记录和用户偏好，生成个性化的当日训练计划。

| 触发方式 | 示例消息 |
|----------|----------|
| 包含 "训练" + 询问意图 | `今天练什么` |
| 包含 "计划" | `给我一个今天的训练计划` |
| 包含 "建议" + 训练 | `训练建议 我想练背` |

**收到回复：** 应用读取你近期的训练记录和偏好（训练水平、目标等），生成一份结构化的训练计划，包含推荐动作、组数、次数建议。

**偏好设置方式：** 发送包含偏好信息的自然语言消息，如 `我喜欢练胸和背，目标是增肌`，应用会自动提取并存储到 `user_preferences` 表中。

#### 1.3 文本摘要 (`summarize_text`)

将用户提供的文本内容总结为结构化摘要：讨论主题、核心结论、待办事项、关键决策。

| 触发方式 | 示例消息 |
|----------|----------|
| 包含 "总结" 或 "摘要" | `总结下面这段话：张三说今天开会讨论了项目进度，李四说需要延期一周...` |
| 包含 "概括" | `概括一下：<大段文本>` |

**收到回复：** 结构化的文本摘要，包含讨论主题、关键结论、待办行动项和决策。

> **注意：** 此功能需要用户直接在消息中提供待总结的文本内容。在群聊场景中，使用 `summarize_group` 意图（触发词"总结"/"摘要"/"概括"/"汇总"）可自动拉取群聊历史消息进行总结，无需手动粘贴内容。

#### 1.4 食谱计划 (`make_meal_plan`)

根据偏好（热量目标、饮食类型、过敏原）生成一日三餐的带营养估算的食谱。

| 触发方式 | 示例消息 |
|----------|----------|
| 包含 "吃什么" | `今天吃什么` |
| 包含 "食谱" | `给我一份低碳水食谱` |
| 包含 "菜单" + 餐相关 | `这周的午餐菜单` |

**收到回复：** 一日三餐的详细菜单，每餐附热量和主要营养素估算。回复内容会参考用户在 `user_preferences` 中存储的饮食偏好（如 `diet_type: ketogenic` 或 `calorie_target: 1800`）。

#### 1.5 个性化问答 (`qa`)

以上四种意图均未匹配时，消息将交由 LLM 进行自由形式问答。适合闲聊、知识查询、个性化建议等场景。

| 触发方式 | 示例消息 |
|----------|----------|
| 任意不在上述规则中的消息 | `我今天的训练量够吗` |
| | `深蹲和腿举哪个对膝盖压力更小` |
| | `推荐几个适合新手的背部动作` |

**收到回复：** LLM 根据上下文和用户偏好生成的个性化回答。

**意图路由优先级：** 关键词规则匹配（"打卡" → `log_training`，"今天练什么" → `today_plan` 等）优先于 LLM 兜底分类，规则命中时置信度为 1.0，零延迟、零 token 消耗。

---

### 2. 调试端点 (POST /api/debug/message)

本地开发用的 HTTP 端点，无需企业微信环境即可测试完整的意图路由和 Agent 处理流程。

**使用方式：**

```bash
curl -X POST http://localhost:8000/api/debug/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"assle","message":"打卡 今天练胸 卧推80kg5组8次"}'
```

**请求格式：**

```json
{
  "user_id": "assle",
  "message": "打卡 今天练胸 卧推80kg5组8次",
  "timestamp": "2026-05-31T16:30:00"
}
```

**返回格式：**

```json
{
  "intent": "log_training",
  "confidence": 1.0,
  "response": "已记录 2 条训练：卧推 80kg 5组8次",
  "data": {
    "records": [
      {
        "muscle_group": "胸",
        "exercise": "卧推",
        "sets": 5,
        "reps": 8,
        "weight_kg": 80.0
      }
    ]
  }
}
```

该端点无需任何企业微信配置即可使用，所有五种意图均可通过此端点测试。

---

### 3. 智能机器人私聊 + 群聊 @回复

通过企业微信智能机器人 URL 回调接入，用户可以在私聊中与机器人对话，或在群聊中 @机器人 触发回复。

**关键点：**
- 需要公网 HTTPS 回调 URL、Token 和 EncodingAESKey
- 回调消息先按 `msgid` 落 SQLite，再后台运行 agent
- 回复通过消息体中的临时 `response_url`
- 消息处理运行在后台 task 中，不会因为 LLM 调用阻塞 HTTP 回调成功响应
- 支持 markdown 格式回复
- 群聊消息自动收集到 SQLite，发送"总结"/"摘要"等触发词时自动生成群聊摘要

**使用方式：**

1. 在企业微信管理后台创建智能机器人，配置 URL 为 `https://<你的域名>/api/wechat/aibot/callback`。
2. 在 `.env` 中填入智能机器人 URL 回调配置：
   ```bash
   WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   WECOM_AIBOT_TOKEN=your-callback-token
   WECOM_AIBOT_ENCODING_AES_KEY=your-43-char-encoding-aes-key
   ```
3. 重启服务，URL 验证通过后即可在私聊或群聊中与机器人交互。

---

### 4. 群聊消息收集与总结

群聊中的文本和语音消息会被自动收集到 SQLite（每次最多保留 200 条/群）。当用户发送包含触发词的消息时，系统会自动拉取近期群聊历史并生成结构化摘要。

| 触发词 | 示例 |
|--------|------|
| 总结 | `@机器人 总结一下今天群消息` |
| 摘要 | `@机器人 摘要最近讨论` |
| 概括 | `@机器人 概括一下大家聊了什么` |
| 汇总 | `@机器人 汇总群聊内容` |

**接收回复：** 结构化的群聊摘要，包含讨论主题、核心结论、待办事项、关键决策。

---

### 5. 语音消息支持

智能机器人支持语音消息 —— 系统提取企业微信内置的语音识别文本后，当作普通文本走完整的意图路由和 agent 管线。

**处理逻辑：**
- 语音识别文本非空 → 正常路由（训练打卡、问训练计划、总结等全部支持）
- 语音识别文本为空 → 静默忽略，不调用 LLM，不回复

**支持场景：**
- 智能机器人私聊：发送语音 → 同上
- 智能机器人群聊 @：发送语音 → 识别文本 → 存 DB → 触发词检测（识别文本中包含"总结"等关键词时触发）

---

### 6. Agent 人格系统

每个 Agent 注入了独立的性格、说话风格和情感基调，让回复自然有人味。

| Agent | 角色名 | 性格底色 |
|-------|--------|----------|
| QA | 小管家 | 细心、温暖、带小幽默，像认识很久的朋友 |
| Fitness | 铁块教练 | 热血、直接，"再来一组"的劲头，讲安全时切回认真模式 |
| Meal | 小厨 | 细心、讲究、对食物有热情，像科普博主 |
| Summary | 会议纪要员 | 客观、条理清晰、抓住重点，不添油加醋 |

---

### 7. 对话记忆系统

QA、Fitness（today_plan）和 Meal 三个 Agent 具备跨轮次对话记忆能力：

- **短期记忆**：最近 6 轮（12 条）消息直接放入 LLM prompt，保持上下文连贯
- **长期记忆**：超出 24 条消息后，最早 12 条由 LLM 压缩为一句摘要，持久化到 SQLite
- **智能压缩**：压缩摘要累积更新，保留关键事实和偏好信息
- **按意图启用**：log_training（单句打卡）和 Summary（每次独立总结）不使用记忆

---

### 当前限制与后续计划

| 状态 | 功能 | 说明 |
|------|------|------|
| 已实现 | 智能机器人私聊 + 群聊 @ | URL 回调入站，msgid 幂等落库，response_url 回复，支持文本和语音 |
| 已实现 | 群聊消息收集 + 触发总结 | 自动存 DB，触发词生成结构化摘要 |
| 暂停 | APScheduler 定时推送 | URL 回调模式不启动 WebSocket，主动推送通道需重新设计 |
| 已实现 | 调试端点 | 本地测试全功能可用 |
| 已实现 | 训练数据持久化 | SQLite 存储，支持历史查询 |
| 已实现 | 用户偏好管理 | 自动提取并持久化偏好 |
| 已实现 | 多轮对话记忆 | 6 轮短期 + LLM 压缩摘要，SQLite 持久化，重启不丢失 |
| 已实现 | agent 人格系统 | 四个 agent 各有独立角色名、说话风格和情感基调 |
| 已实现 | 多消息类型支持 | 文本 + 语音（提取企业微信内置识别文本后路由） |
| 已实现 | RAG Stage 1 知识库 | SQLite 文档/分块存储，本地 `.md`/`.txt` 导入，QAAgent 检索注入 |
| 未实现 | RAG Stage 2/3 | 向量/混合检索、PDF/web 导入、文件上传与索引重建 |

详见 [`docs/agent/upgrade-roadmap.md`](docs/agent/upgrade-roadmap.md)。

## License

MIT
