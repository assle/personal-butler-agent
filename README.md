# Personal Butler Agent

基于企业微信的 AI 私人管家系统 —— 通过自然语言交互管理健身、饮食、群聊总结等日常事务。

## 架构概览

```
用户 → 企业微信自建应用 → FastAPI 回调接口 → Intent Router (规则 + LLM)
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
                                    ┌─────────┴──────────┐
                                    ↓                    ↓
                              自建应用私发          群机器人推送
```

**七层设计：**

| 层 | 技术 | 说明 |
|----|------|------|
| 自建应用 | 企业微信 | 交互入口，接收用户指令 |
| 群机器人 | Webhook | 公告、日报、通知推送到群 |
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
│   ├── main.py              # FastAPI 应用入口 + AgentRegistry 注册 + 条件启动企业微信路由
│   ├── config.py            # .env 配置加载（LLM / DB / 企业微信）
│   ├── router/
│   │   └── debug.py         # POST /api/debug/message（本地调试端点）
│   ├── wechat/              # 企业微信集成模块
│   │   ├── crypto.py        # AES-256-CBC 加解密 + SHA1 签名验证
│   │   ├── messages.py      # XML 解析/构建 + 消息数据类
│   │   ├── webhook.py       # 群机器人 Webhook 推送客户端
│   │   └── router.py        # GET/POST /api/wechat/callback
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
│   ├── models/
│   │   ├── training.py      # 训练记录 ORM
│   │   └── preference.py    # 用户偏好 ORM (JSON)
│   ├── schemas/
│   │   ├── request.py       # 请求 Schema
│   │   └── response.py      # 响应 Schema
│   ├── llm/
│   │   └── client.py        # ChatOpenAI 封装（DeepSeek 兼容）
│   └── db/
│       ├── base.py          # SQLAlchemy DeclarativeBase
│       └── session.py       # 异步引擎 + 会话工厂 + get_db 依赖注入
├── tests/                   # 47 个测试
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

### GET/POST /api/wechat/callback

企业微信自建应用回调。**仅当 `.env` 中 `WECHAT_CORP_ID` 和 `WECHAT_TOKEN` 均配置时注册。**

| 方法 | 用途 | 说明 |
|------|------|------|
| GET | URL 验证 | 企业微信后台配置回调 URL 时触发，验证签名并解密 echostr |
| POST | 消息接收 | 用户在企业微信中发送消息时触发，解密 → 意图路由 → agent 回复 → 加密返回 |

详细设计见 `docs/superpowers/specs/2026-05-30-wechat-work-integration-design.md`。

## 支持的意图

| 意图 | 触发方式 | 功能 |
|------|----------|------|
| `log_training` | "打卡 练胸..." / "记录训练" | 自然语言记录训练数据 |
| `today_plan` | "今天练什么" / "训练建议" | 基于历史和偏好生成训练计划 |
| `summarize_text` | "帮我总结..." / "summary" | 结构化的群聊文本总结 |
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

### 自建应用回调

- 用户在企业微信中给自建应用发消息 → 企业微信 POST 加密 XML 到 `/api/wechat/callback`
- 加密方案：AES-256-CBC + PKCS#7 padding + SHA1 签名验证
- 回调 URL 和 Token/EncodingAESKey 在企业微信管理后台配置

### 群机器人 Webhook

- `WechatWebhookClient` 通过 HTTP POST 向群 Webhook URL 推送 text/markdown 消息
- 配置 `WECHAT_WEBHOOK_URL` 后自动创建客户端实例

### 配置变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `WECHAT_CORP_ID` | 回调必需 | 企业 CorpID |
| `WECHAT_TOKEN` | 回调必需 | URL 验证 Token |
| `WECHAT_ENCODING_AES_KEY` | 回调必需 | 消息加解密 AES 密钥 |
| `WECHAT_AGENT_ID` | 否 | 应用 AgentId |
| `WECHAT_WEBHOOK_URL` | 推送必需 | 群机器人 Webhook 地址 |

## 数据库

使用 SQLite 本地文件存储，两张核心表：

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
# 运行全部测试（47 个）
DEEPSEEK_API_KEY=test uv run pytest -q

# 运行单个模块
DEEPSEEK_API_KEY=test uv run pytest tests/test_fitness.py -v

# 运行企业微信模块测试
DEEPSEEK_API_KEY=test uv run pytest tests/test_wechat_crypto.py tests/test_wechat_messages.py -v
```

## 已实现功能

以下功能已完整实现端到端工作流，从用户输入到应用回复全过程无错误且返回正确结果。

---

### 1. 自建应用私聊问答

用户在企业微信中向自建应用发送消息，应用经过「解密 → 意图识别 → LLM 处理 → 加密回复」链路，返回 AI 生成的回答。

**使用方式：**

1. 在企业微信管理后台创建自建应用，配置回调 URL 为 `https://<你的域名>/api/wechat/callback`
2. 在 `.env` 中填入企业微信配置：
   ```bash
   WECHAT_CORP_ID=ww1234567890abcdef      # 企业 CorpID
   WECHAT_TOKEN=your_token_here           # 回调 Token
   WECHAT_ENCODING_AES_KEY=your_aes_key   # 43 位 EncodingAESKey
   ```
3. 重启服务，在企业微信中找到该自建应用，发送消息即可

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

#### 1.3 群聊文本总结 (`summarize_text`)

将群聊中的多轮对话整理为结构化的摘要：核心结论、待办事项、关键分歧。

| 触发方式 | 示例消息 |
|----------|----------|
| 包含 "总结" 或 "摘要" | `帮我总结一下刚才的聊天记录` |
| 包含 "概括" | `概括一下上面的讨论` |
| 附带聊天记录的引用文本 | `总结下面这段话：<聊天记录>` |

**收到回复：** 结构化的文本摘要，包含讨论主题、核心结论、待办行动项和关键分歧点。

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

### 当前限制与后续计划

| 状态 | 功能 | 说明 |
|------|------|------|
| 已实现 | 自建应用私聊问答 | 五种意图完整可用 |
| 已实现 | 调试端点 | 本地测试全功能可用 |
| 已实现 | 训练数据持久化 | SQLite 存储，支持历史查询 |
| 已实现 | 用户偏好管理 | 自动提取并持久化偏好 |
| 已实现 | 多轮对话记忆 | MemorySaver checkpointing（进程内，重启丢失） |
| 已有客户端未接入 | 群机器人 Webhook 推送 | `WechatWebhookClient` 已实现并通过测试，但尚未与 Agent 和定时任务对接 |
| 未实现 | APScheduler 定时任务 | 日报推送、训练提醒等定时场景 |
| 未实现 | 对话记忆持久化 | MemorySaver → SqliteSaver，重启后保留对话上下文 |
| 未实现 | 客服消息异步回复 | 突破企业微信被动回复的 5 秒超时限制 |
| 未实现 | RAG 知识库 | 查询外部知识增强回答 |

详见 [`docs/agent/upgrade-roadmap.md`](docs/agent/upgrade-roadmap.md)。

## License

MIT
