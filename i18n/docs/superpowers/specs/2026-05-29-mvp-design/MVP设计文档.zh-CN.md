# 个人管家代理 MVP 设计规范

## 概述

基于企业微信的MVP 个人管家系统。用户通过企业微信自建应用发送命令，后端Agent处理意图路由、调用业务模块、读写SQLite数据库、生成结果，并通过自建应用私信或群机器人Webhook推送进行回复。

## 技术堆栈

| 层 | 选择 |
|-------|--------|
| 运行时 | Python 3.13+ |
| Web 框架 | FastAPI |
| ORM | SQLAlchemy + SQLite |
| 数据验证 | Pydantic |
| 调度程序 | APScheduler（内存模式） |
| 包管理器 | uv |
| 测试 | py测试 |
| LLM | DeepSeek API (`deepseek-v4-pro`)，OpenAI 兼容客户端 |

**限制：** 没有 Redis、Celery、Kafka、Docker、Kubernetes。单进程部署。

## 架构

```
User → WeChat Work Self-Built App → FastAPI Callback → Intent Router
                                                          ↓
                                                ┌─────────┴──────────┐
                                                ↓         ↓          ↓
                                            Fitness   Summary    Meal / QA
                                                ↓         ↓          ↓
                                                └─────────┬──────────┘
                                                          ↓
                                                    SQLite Database
                                                          ↓
                                                ┌─────────┬──────────┐
                                                ↓                    ↓
                                          Self-Built App        Group Bot
                                          Private Reply        Webhook Push
```

六层：
- **自建应用**=交互入口
- **群机器人** = 主动推送出口
- **SQLite** = 内存层
- **LLM** = 解析并生成层
- **规则引擎** = 稳定的决策层
- **调度程序** = 定时触发器

## 项目结构

```
personal_butler_agent/
├── src/
│   ├── __init__.py
│   ├── main.py                # FastAPI app entry point
│   ├── config.py              # .env config loader
│   ├── router/
│   │   ├── __init__.py
│   │   └── debug.py           # POST /api/debug/message
│   ├── intent/
│   │   ├── __init__.py
│   │   ├── router.py          # IntentRouter: rules → LLM fallback
│   │   └── rules.py           # Keyword/regex rule sets
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py            # Agent abstract base class
│   │   ├── fitness.py         # Fitness Agent
│   │   ├── summary.py         # Summary Agent
│   │   ├── meal.py            # Meal Agent
│   │   └── qa.py              # QA Agent
│   ├── models/
│   │   ├── __init__.py
│   │   ├── training.py        # TrainingRecord ORM
│   │   └── preference.py      # UserPreference ORM (JSON preferences)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── request.py         # Pydantic request schemas
│   │   └── response.py        # Pydantic response schemas
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py          # OpenAI-compatible client (DeepSeek)
│   └── db/
│       ├── __init__.py
│       ├── session.py         # Database session factory
│       └── base.py            # SQLAlchemy declarative base
├── tests/
│   ├── __init__.py
│   ├── test_intent.py
│   ├── test_fitness.py
│   ├── test_summary.py
│   ├── test_meal.py
│   └── test_qa.py
├── .env.example
├── .gitignore
├── pyproject.toml
└── uv.lock
```

## 数据库设计

### 训练记录

| 柱子 | 类型 | 描述 |
|--------|------|-------------|
| ID | 整数PK | 自动递增 |
| 用户身份 | 文本不为空 | 用户标识符 |
| 日期 | 文本不为空 | 培训日期 YYYY-MM-DD |
| 肌肉群 | 文本不为空 | 目标肌群 |
| 锻炼 | 文本不为空 | 练习名称 |
| 套 | 整数不为空 | 套数 |
| 代表 | 整数不为空 | 每组次数 |
| 体重kg | 真实的 | 体重，体重可为空 |
| 创建时间 | 文本 | 创建时间戳 |

### 用户偏好

| 柱子 | 类型 | 描述 |
|--------|------|-------------|
| ID | 整数PK | 自动递增 |
| 用户身份 | 文本不为空唯一 | 用户标识符 |
| 偏好 | 文本不为空 | JSON blob，按命名空间组织 |
| 创建时间 | 文本 | 创建时间戳 |
| 更新时间 | 文本 | 最后更新时间戳 |

默认首选项 JSON：

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

首选项是可扩展的——新模块在 JSON 根下添加自己的命名空间。无需架构迁移。 Pydantic 验证已知的命名空间；未知的命名空间不变地通过。

## 意图路由器

两层路由：**规则第一，LLM 后备。**

```
User Message
  ↓
Rule Layer (rules.py)
  ├── Keyword match hit → return (intent, confidence=1.0)
  └── No match
        ↓
LLM Fallback (router.py)
  └── Send message + intent list to DeepSeek
     → return classification (intent, confidence)
```

### 意图类型

| 意图 | 触发关键词 |
|--------|-----------------|
| `log_training` | 打卡, 记录训练, 练了, 训练 |
| `today_plan` | 今天练什么, 今日计划, 训练建议 |
| `summarize_text` | 总结，总结，帮我总结 |
| `make_meal_plan` | 食谱、吃什么、膳食计划、饮食 |
| `qa` | 非空消息的默认回退 |
| `unknown` | 无法识别的输入 |

### LLM后备

系统提示列出了 6 个意图并附有说明。模型返回：

```json
{"intent": "qa", "confidence": 0.85}
```

硬性规则：如果 LLM 返回的意图不在已知列表中，则回退到 `unknown`。

## 健身代理

### 日志训练

用户发送自然语言→LLM提取结构化数据→验证→写入`training_records`。

```
"打卡 今天练胸 卧推80kg5组8次 飞鸟15kg3组12次"
  → LLM extract → [
    {date:"2026-05-29", muscle_group:"胸", exercise:"卧推", sets:5, reps:8, weight_kg:80},
    {date:"2026-05-29", muscle_group:"胸", exercise:"飞鸟", sets:3, reps:12, weight_kg:15}
  ]
  → Write to DB → Return confirmation
```

提取失败时，返回错误并提供格式指导。

### 今天的计划

查询近期训练记录（7天）+用户健身偏好→LLM生成今日建议。

```
Input: last 7 days training records + fitness preferences
Output: suggested muscle group, exercises, sets/reps in natural language
```

规则层保护：如果某个肌肉群最近没有训练过，则优先考虑它以避免 LLM 建议不平衡。

## 摘要代理

用户发送包含聊天文本的消息 → LLM 生成结构化摘要。

输入：原始聊天记录文本。
输出格式：

```
讨论主题：xxx
关键结论：
  - Conclusion 1
  - Conclusion 2
待办事项：
  - @person Task
决策：xxx
```

MVP：聊天消息没有持久性。一项要求，一项总结。

## 膳食代理

输入：用户`meal`偏好+近期训练记录。

LLM生成全天膳食计划（早餐、午餐、晚餐），其中包含每项营养估算，信息包括：

- 身体数据（身高/体重→估计BMR）
- 饮食偏好（卡路里目标、饮食类型、过敏）
- 近期训练（训练→高蛋白、休息日→维持）

输出格式：

```
早餐 (≈XXX kcal)
- Food 1 (Protein Xg, Carbs Xg, Fat Xg)
- Food 2
午餐 (≈XXX kcal)
- ...
晚餐 (≈XXX kcal)
- ...
```

## 质量检查代理

最简单的代理：用户消息→发送给LLM，并在系统提示中显示用户偏好以获取个性化提示音→返回响应。

没有拉格。没有多次获得 MVP 的历史。

## 请求/响应架构

### 请求：`POST /api/debug/message`

```json
{
  "user_id": "assle",
  "message": "今天练了胸 卧推80kg5组8次",
  "timestamp": "2026-05-29T16:30:00"
}
```

### 回复

```json
{
  "intent": "log_training",
  "confidence": 1.0,
  "response": "已记录训练：胸 - 卧推 80kg 5组x8次",
  "data": {}
}
```

来自意图路由器的 `intent` + `confidence`。 `response` 是智能体的自然语言输出。 `data`携带结构化负载（训练记录、膳食计划、总结等）。

## MVP 范围

### 包括
- `POST /api/debug/message` 端点
- 具有规则的意图路由器 + LLM 回退（6 个意图）
- 健身：日志_训练 + 今天_计划
- 摘要：结构化聊天摘要
- 膳食：生成上下文每日膳食计划
- QA：一般问题回答
- SQLite 持久化训练记录和用户偏好

### 排除
- 真正的企业微信回调集成（仅限调试端点）
- 群机器人 Webhook 推送
- APScheduler 定时任务
- 多轮对话历史记录
- RAG/知识库
- 多用户群聊消息采集
