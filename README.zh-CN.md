# Personal Butler Agent

[中文](README.md)

基于企业微信的AI私人管家系统——通过自然语言交互管理健身、膳食、群聊总结、日常任务。

## 架构概述

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

**七层设计：**

| 层 | 技术 | 描述 |
|----|------|------|
| 自建应用 | 企业微信 | 交互入口点，接收用户命令 |
| 群机器人 | Webhook | 公告、日报、群组通知推送 |
| 智能体编排 | LangGraph 状态图 | 状态机驱动、多步推理、条件路由 |
| LLM | LangChain ChatOpenAI → DeepSeek | 意图理解、内容生成、结构化提取 |
| 规则引擎 | 关键词匹配 | 确定性路由，零成本 |
| 内存层 | SQLite + MemorySaver | 持久化偏好/训练记录 + 多轮对话 checkpoint |
| 调度程序 | APScheduler | 计划任务驱动程序（每日报告、提醒） |

## 技术堆栈

| 组件 | 选择 |
|------|------|
| 运行时 | Python 3.13+ |
| Web 框架 | FastAPI |
| 智能体框架 | LangGraph + LangChain |
| LLM | langchain-openai → DeepSeek API |
| 企业微信加密 | 密码学 (AES-256-CBC) |
| ORM | SQLAlchemy 2.0（异步）+ aiosqlite |
| 数据验证 | Pydantic v2 |
| 计划任务 | APScheduler |
| 包管理器 | uv |
| 测试 | pytest + pytest-asyncio |

## 项目结构

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
│   │   └── memory.py        # LangGraph MemorySaver 共享实例
│   ├── memory/
│   │   ├── __init__.py
│   │   └── conversation.py  # 对话记忆管理模块
│   ├── models/
│   │   ├── training.py      # Training record ORM
│   │   ├── preference.py    # User preference ORM (JSON)
│   │   ├── group_message.py # 群聊消息 ORM
│   │   └── conversation.py  # 对话记忆 ORM（消息 + 摘要压缩）
│   ├── schemas/
│   │   ├── request.py       # Request schemas
│   │   └── response.py      # Response schemas
│   ├── llm/
│   │   └── client.py        # ChatOpenAI wrapper (DeepSeek-compatible)
│   └── db/
│       ├── base.py          # SQLAlchemy DeclarativeBase
│       └── session.py       # Async engine + session factory + get_db dependency injection
├── tests/                   # 96 个测试
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

## 快速入门

### 开发环境（本地）

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

### 生产环境（云服务器）

请参阅 [`部署指南.md`](部署指南.md) — 使用 uv + Caddy + systemd 从头开始​​完成步骤。

## API端点

### POST /api/调试/消息

本地调试端点，模拟企业微信消息回调。始终可用，无需企业微信配置。

**要求：**

```json
{
  "user_id": "assle",
  "message": "打卡 今天练胸 卧推80kg5组8次",
  "timestamp": "2026-05-29T16:30:00"
}
```

| 字段 | 类型 | 是否必填 | 描述 |
|------|------|------|------|
| 用户身份 | 细绳 | 是的 | 用户标识符 |
| 信息 | 细绳 | 是的 | 留言内容 |
| 时间戳 | 日期时间 | 否 | 消息时间 |

**回复：**

```json
{
  "intent": "log_training",
  "confidence": 1.0,
  "response": "已记录 2 条训练：卧推、飞鸟",
  "data": { "records": [{ "muscle_group": "胸", "exercise": "卧推", ... }] }
}
```

| 字段 | 类型 | 描述 |
|------|------|------|
| 意图 | 细绳 | 公认的意图 |
| 信心 | 漂浮 | 置信度0.0-1.0 |
| 回复 | 细绳 | 回复文字 |
| 数据 | 目的 | 结构化数据（可选） |

### GET/POST /api/微信/回调

企业微信自建应用回调。 **仅当 `.env` 中同时配置了 `WECHAT_CORP_ID` 和 `WECHAT_TOKEN` 时才注册。**

| 方法 | 目的 | 描述 |
|------|------|------|
| 得到 | 网址验证 | 企业微信后台配置回调 URL时触发；验证签名并解密 echostr |
| 邮政 | 留言接收 | 用户在企业微信中发送消息时触发；解密 → 意图路由 → 代理回复 → 加密返回 |

详细设计参见`docs/superpowers/specs/2026-05-30-wechat-work-integration-design.md`。

## 支持的意图

| 意图 | 扳机 | 功能 |
|------|----------|------|
| `log_training` | "打卡 练胸..." / "记录训练" | 自然语言训练记录记录 |
| `today_plan` | "今天练什么" / "训练建议" | 根据历史和偏好生成培训计划 |
| `summarize_text` | “帮我总结...”/“总结” | 结构化私人聊天文本摘要 |
| `summarize_group` | “@bot 总结了一些消息” | 结构化群聊历史汇总 |
| `make_meal_plan` | "今天吃什么" / "食谱" | 生成全天膳食计划以及营养估算 |
| `qa` | 默认回退 | 个性化问答 |
| `unknown` | 无法辨认 | 返回提示信息 |

**意图路由策略：**关键字规则优先（确定性，零成本）。不匹配的消息回落到LangChain ChatOpenAI调用DeepSeek进行分类。

## 代理架构

每个Agent都是一个LangGraph `StateGraph`，由三部分组成：

| 文件 | 责任 |
|------|------|
| `state.py` | TypedDict 定义图状态 |
| `nodes.py` | 单职责异步节点功能（提取/验证/生成/格式化等） |
| `graph.py` | StateGraph组件+Agent类（提供`handle()`入口点） |

**FitnessAgent 示例：**

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

添加新Agent：创建`state.py` + `nodes.py` + `graph.py`→通过`agent_registry.register(intent, agent)`在`src/main.py`中注册。

## 企业微信集成

### 自建应用回调

- 用户向企业微信自建应用发送消息→企业微信POST加密XML到`/api/wechat/callback`
- 加密：AES-256-CBC + PKCS#7 填充 + SHA1 签名验证
- 回调 URL、Token、EncodingAESKey在企业微信管理控制台配置

### 群机器人 Webhook

- `WechatWebhookClient` 通过 HTTP POST 将文本/markdown 消息推送到群 Webhook URL
- 配置 `WECHAT_WEBHOOK_URL` 时自动创建客户端实例

### 配置变量

| 变量 | 是否必填 | 描述 |
|------|------|------|
| `WECHAT_CORP_ID` | 回调需要 | 企业公司ID |
| `WECHAT_TOKEN` | 回调需要 | URL 验证令牌 |
| `WECHAT_ENCODING_AES_KEY` | 回调需要 | 消息加密/解密 AES 密钥 |
| `WECHAT_AGENT_ID` | 否 | 应用 AgentId |
| `WECHAT_WEBHOOK_URL` | 需要推送 | 群机器人 Webhook URL |

## 数据库

SQLite本地文件存储具有五张核心表：

**training_records** — 训练记录

| 柱子 | 类型 | 描述 |
|----|------|------|
| ID | 整数PK | 自动递增 |
| 用户身份 | 文本不为空 | 用户标识符 |
| 日期 | 文本不为空 | 培训日期 YYYY-MM-DD |
| 肌肉群 | 文本不为空 | 目标肌群 |
| 锻炼 | 文本不为空 | 练习名称 |
| 套 | 整数不为空 | 套数 |
| 代表 | 整数不为空 | 每组次数 |
| 体重kg | 真实的 | 重量 |
| 创建时间 | 文本 | 创建时间戳 |

**user_preferences** — 用户首选项

| 柱子 | 类型 | 描述 |
|----|------|------|
| ID | 整数PK | 自动递增 |
| 用户身份 | 文本不为空唯一 | 用户标识符 |
| 偏好 | 文本不为空 | JSON 首选项（按命名空间组织） |

**conversation_messages** — 对话消息

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| user_id | TEXT NOT NULL INDEXED | 用户标识 |
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

**group_messages** — 群聊消息

| 柱子 | 类型 | 描述 |
|----|------|------|
| ID | 整数PK | 自动递增 |
| 聊天ID | 文本不为空索引 | 群聊ID |
| 用户身份 | 文本不为空 | 发件人标识符 |
| 内容 | 文本不为空 | 留言内容 |
| 创建时间 | 整数不为空 | 消息时间戳 |

preferences JSON 结构是可扩展的，新模块只需添加自己的 namespace：

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
# Run all tests (96)
DEEPSEEK_API_KEY=test uv run pytest -q

# Run a single module
DEEPSEEK_API_KEY=test uv run pytest tests/test_fitness.py -v

# Run WeChat Work module tests
DEEPSEEK_API_KEY=test uv run pytest tests/test_wechat_crypto.py tests/test_wechat_messages.py -v
```

## 实现的功能

以下功能具有完整的端到端工作流程，从用户输入到应用响应，零错误和正确的结果。

---

### 1. 自建应用私聊问答

用户向企业微信自建应用发送消息。应用通过以下方式处理它们：解密→意图识别→LLM处理→加密回复。

**用法：**

1. 在企业微信管理控制台创建一个自建应用，回调地址设置为`https://<your-domain>/api/wechat/callback`
2. 在`.env`中填写企业微信配置：
   ```bash
   WECHAT_CORP_ID=ww1234567890abcdef      # Enterprise CorpID
   WECHAT_TOKEN=your_token_here           # Callback Token
   WECHAT_ENCODING_AES_KEY=your_aes_key   # 43-char EncodingAESKey
   ```
3. 重启服务并向企业微信自建应用发送消息

**五个集成意图和使用示例：**

#### 1.1 训练记录（`log_training`）

使用多种练习、重量、组数和次数的自然语言描述来记录健身训练数据。

| 扳机 | 消息示例 |
|----------|----------|
| 包含“打卡” | `打卡 今天练胸 卧推80kg5组8次 飞鸟15kg4组12次` |
| 包含“记录训练” | `记录训练 深蹲100kg5x5 腿举200kg3x10` |

#### 1.2 训练计划建议（`today_plan`）

根据历史训练记录和用户偏好生成个性化的日常训练计划。

| 扳机 | 消息示例 |
|----------|----------|
| 包含“训练”+查询意图 | `今天练什么` |
| 包含“计划” | `给我一个今天的训练计划` |
| 包含“建议”+培训 | `训练建议 我想练背` |

#### 1.3 文字总结（`summarize_text`）

将用户提供的文本总结为结构化格式：讨论主题、关键结论、行动项目和决策。

| 扳机 | 消息示例 |
|----------|----------|
| 包含“总结”或“摘要” | `总结下面这段话：张三说今天开会讨论了项目进度...` |
| 包含“百年” | `概括一下：<long text>` |

#### 1.4 群聊总结（`summarize_group`）

使用@mention + 总结关键字触发群聊摘要。所有群消息都是被动收集的；只有触发消息才会生成回复。

| 扳机 | 消息示例 |
|----------|----------|
| 群聊+摘要关键词 | `@bot 总结一下群消息` |
|  | `@bot 摘要` / `@bot 概括` / `@bot 汇总` |

#### 1.5 膳食计划（`make_meal_plan`）

根据偏好（卡路里目标、饮食类型、过敏）生成全天膳食计划和营养估计。

| 扳机 | 消息示例 |
|----------|----------|
| 含有“吃什么” | `今天吃什么` |
| 包含“食谱” | `给我一份低碳水食谱` |

#### 1.6 个性化问答（`qa`）

当上述意图都不匹配时，消息将通过 LLM 路由到自由格式的问答。

| 扳机 | 消息示例 |
|----------|----------|
| 任何不符合上述规则的消息 | `我今天的训练量够吗` |

---

### 2. Agent 人格系统

每个 Agent 注入了独立的性格、说话风格和情感基调，让回复自然有人味。

| Agent | 角色名 | 性格底色 |
|-------|--------|----------|
| QA | 小管家 | 细心、温暖、带小幽默，像认识很久的朋友 |
| Fitness | 铁块教练 | 热血、直接，"再来一组"的劲头，讲安全时切回认真模式 |
| Meal | 小厨 | 细心、讲究、对食物有热情，像科普博主 |
| Summary | 会议纪要员 | 客观、条理清晰、抓住重点，不添油加醋 |

---

### 3. 对话记忆系统

QA、Fitness（today_plan）和 Meal 三个 Agent 具备跨轮次对话记忆能力：

- **短期记忆**：最近 6 轮（12 条）消息直接放入 LLM prompt，保持上下文连贯
- **长期记忆**：超出 24 条消息后，最早 12 条由 LLM 压缩为一句摘要，持久化到 SQLite
- **智能压缩**：压缩摘要累积更新，保留关键事实和偏好信息
- **按意图启用**：log_training（单句打卡）和 Summary（每次独立总结）不使用记忆

---

### 2. 调试端点（POST /api/debug/message）

本地开发 HTTP 端点，用于在没有企业微信的情况下测试完整的意图路由和智能体管道。

**用法：**

```bash
curl -X POST http://localhost:8000/api/debug/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"assle","message":"打卡 今天练胸 卧推80kg5组8次"}'
```

支持`chat_type`和`chat_id`字段，用于模拟群聊场景。

### 当前的限制和后续步骤

| 地位 | 特征 | 描述 |
|------|------|------|
| 实施的 | 自建app私聊问答 | 所有意图功能齐全 |
| 实施的 | 调试端点 | 完整的本地测试能力 |
| 实施的 | 训练数据持久化 | 带有历史查询的 SQLite 存储 |
| 实施的 | 用户偏好管理 | 自动提取并保留首选项 |
| 已实施 | 多轮对话记忆 | 6 轮短期 + LLM 压缩摘要，SQLite 持久化，重启不丢失 |
| 已实施 | Agent 人格系统 | 四个 agent 各有独立角色名、说话风格和情感基调 |
| 已实施 | 群聊总结 | 被动采集+触发式汇总 |
| 客户端存在，未连接 | 群机器人 Webhook 推送 | `WechatWebhookClient` 已实施并测试，尚未连接到代理和调度程序 |
| 未实施 | APScheduler 定时任务 | 每日推送、训练提醒等 |
| 未实施 | 异步客服回复 | 克服企业微信被动回复5秒超时问题 |
| 未实施 | RAG知识库 | 利用外部知识增强答案 |

详情请参见[`docs/agent/upgrade-roadmap.md`](docs/agent/upgrade-roadmap.md)。

## 执照

麻省理工学院
