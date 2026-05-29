# Personal Butler Agent

基于企业微信的 AI 私人管家系统 —— 通过自然语言交互管理健身、饮食、群聊总结等日常事务。

## 架构概览

```
用户 → 企业微信自建应用 → FastAPI 回调接口 → Intent Router
                                                  ↓
                                        ┌─────────┴──────────┐
                                        ↓         ↓          ↓
                                    Fitness   Summary    Meal / QA
                                        ↓         ↓          ↓
                                        └─────────┬──────────┘
                                                  ↓
                                            SQLite 数据库
                                                  ↓
                                        ┌─────────┬──────────┐
                                        ↓                    ↓
                                  自建应用私发          群机器人推送
```

**六层设计：**

| 层 | 角色 | 说明 |
|----|------|------|
| 自建应用 | 交互入口 | 接收用户指令，私发回复 |
| 群机器人 | 推送出口 | 公告、日报、通知推送到群 |
| SQLite | 记忆层 | 持久化用户偏好、训练历史 |
| LLM | 解析和生成层 | 意图理解、内容生成、自然语言处理 |
| 规则模块 | 稳定决策层 | 关键词匹配确定性路由 |
| Scheduler | 定时触发器 | 定时任务驱动（日报、提醒） |

## 技术栈

| 组件 | 选型 |
|------|------|
| Runtime | Python 3.13+ |
| Web 框架 | FastAPI |
| ORM | SQLAlchemy 2.0 (async) + aiosqlite |
| 数据校验 | Pydantic v2 |
| 定时任务 | APScheduler |
| 包管理 | uv |
| 测试 | pytest + pytest-asyncio |
| LLM | DeepSeek API (OpenAI 兼容) |

## 项目结构

```
personal_butler_agent/
├── src/
│   ├── main.py              # FastAPI 应用入口
│   ├── config.py            # .env 配置加载
│   ├── router/
│   │   └── debug.py         # POST /api/debug/message
│   ├── intent/
│   │   ├── rules.py         # 关键词规则匹配
│   │   └── router.py        # 规则优先 + LLM 兜底路由
│   ├── agents/
│   │   ├── base.py          # BaseAgent 抽象基类
│   │   ├── fitness.py       # 健身 Agent
│   │   ├── summary.py       # 群聊总结 Agent
│   │   ├── meal.py          # 食谱 Agent
│   │   └── qa.py            # 问答 Agent
│   ├── models/
│   │   ├── training.py      # 训练记录 ORM
│   │   └── preference.py    # 用户偏好 ORM (JSON)
│   ├── schemas/
│   │   ├── request.py       # 请求 Schema
│   │   └── response.py      # 响应 Schema
│   ├── llm/
│   │   └── client.py        # DeepSeek API 客户端
│   └── db/
│       ├── base.py          # SQLAlchemy Base
│       └── session.py       # 异步引擎 + 会话工厂
├── tests/                   # 29 个测试
├── docs/superpowers/
│   ├── specs/               # 设计文档
│   └── plans/               # 实现计划
├── pyproject.toml
└── .env.example
```

## 快速开始

### 1. 环境准备

```bash
# 安装 uv (如果还没有)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装依赖
uv sync
```

### 2. 配置 LLM

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 DeepSeek API Key：

```
DEEPSEEK_API_KEY=sk-your-actual-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite+aiosqlite:///butler.db
```

### 3. 启动服务

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### 4. 测试调用

```bash
curl -X POST http://localhost:8000/api/debug/message \
  -H "Content-Type: application/json" \
  -d '{"user_id":"assle","message":"打卡 今天练胸 卧推80kg5组8次"}'
```

## API 文档

### POST /api/debug/message

模拟发送消息给机器人（MVP 阶段使用此接口代替企业微信回调）。

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

| 字段 | 类型 | 说明 |
|------|------|------|
| intent | string | 识别的意图 |
| confidence | float | 置信度 0.0-1.0 |
| response | string | 回复文本 |
| data | object | 结构化数据（可选） |

## 支持的意图

| 意图 | 触发方式 | 功能 |
|------|----------|------|
| `log_training` | "打卡 练胸..." / "记录训练" | 自然语言记录训练数据 |
| `today_plan` | "今天练什么" / "训练建议" | 基于历史和偏好生成训练计划 |
| `summarize_text` | "帮我总结..." / "summary" | 结构化的群聊文本总结 |
| `make_meal_plan` | "今天吃什么" / "食谱" | 生成带营养估算的一日三餐 |
| `qa` | 默认兜底 | 个性化问答 |
| `unknown` | 无法识别时 | 返回错误提示 |

**意图路由策略：** 关键词规则优先（确定性、零成本），未命中时由 DeepSeek LLM 兜底分类。

## 功能模块

### 健身 Agent

- **记录训练：** LLM 从自然语言提取结构化数据（部位、动作、组数、次数、重量），校验后写入 SQLite
- **训练计划：** 查询近 7 天训练记录 + 用户偏好，LLM 生成部位轮换建议

### 总结 Agent

- 输入群聊文本 → LLM 输出结构化摘要（讨论主题 / 关键结论 / 待办事项 / 决策）

### 食谱 Agent

- 根据用户身体数据、饮食偏好、当日训练状态 → 生成带营养素估算是三餐建议

### 问答 Agent

- 注入用户偏好的个性化问答

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
# 运行全部测试
DEEPSEEK_API_KEY=test uv run pytest tests/ -v

# 运行单个模块
DEEPSEEK_API_KEY=test uv run pytest tests/test_fitness.py -v
```

## MVP 范围

**已实现：**
- `POST /api/debug/message` 调试端点
- 意图路由（规则 + LLM 兜底，6 种意图）
- 健身/总结/食谱/问答四个 Agent
- SQLite 持久化训练记录和用户偏好
- 29 个测试覆盖

**后续计划：**
- 企业微信自建应用回调对接
- 群机器人 Webhook 推送
- APScheduler 定时任务（日报、提醒）
- 多轮对话上下文记忆
- RAG 知识库集成

## License

MIT
