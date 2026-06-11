# Personal Butler Agent

[English](README.en.md)

基于企业微信智能机器人的 AI 私人管家系统。当前版本采用 scene-agent 架构：私聊、群聊 @、定时群 webhook 推送分别走独立 agent，避免把不同场景混在同一条全局意图路由里。

## 当前接口

| 接口 | 路径/配置 | 用途 |
|------|-----------|------|
| 智能机器人 URL 回调 | `GET/POST /api/wechat/aibot/callback` | 企业微信 URL 验证、消息回调、`response_url` 被动回复 |
| 企业微信群 webhook 推送 | `SCHEDULER_TARGETS_FILE` | APScheduler 按 JSON 配置定时生成或原样拼接并推送群 markdown |

项目不再暴露本地 debug/dev 消息 API；本地联调请通过 HTTPS 隧道或生产 HTTPS 配置企业微信智能机器人 URL 回调。

## 架构概览

```text
企业微信智能机器人 URL 回调
  -> callback_router 解密、验签、按 msgid 幂等落库
  -> callback_handler 规范化为 InboundMessage
  -> dispatch_message 按场景分发
       ├─ single -> PrivateButlerAgent
       │            └─ LangGraph tool-calling -> Summary / Knowledge / Web Search / Weather / Reminder
       └─ group  -> apply_group_policy 保存群消息、判断触发
                    └─ GroupMentionAgent -> 群总结 / 真实天气 / 简单问答 / 越界拒绝

APScheduler
  -> SchedulerManager
  -> SchedulerManager 按 target mode 生成或拼接最终 markdown 正文
  -> WebhookPushClient 发送到企业微信群 webhook
```

## 技术栈

| 组件 | 选型 |
|------|------|
| Runtime | Python 3.13+ |
| Web 框架 | FastAPI |
| Agent 框架 | LangGraph + LangChain |
| LLM | langchain-openai -> DeepSeek/OpenAI-compatible API |
| 企业微信加解密 | cryptography (AES-256-CBC) |
| ORM | SQLAlchemy 2 async + aiosqlite |
| 数据校验 | Pydantic v2 |
| 定时任务 | APScheduler |
| 包管理 | uv |
| 测试 | pytest + pytest-asyncio |

## 主要能力

| 场景 | Agent | 能力 |
|------|-------|------|
| 私聊 | `PrivateButlerAgent` | 自然对话、文本摘要、本地知识库检索、联网搜索、天气查询、创建/查看/取消群 webhook 提醒 |
| 群聊 @ | `GroupMentionAgent` | 群聊总结、真实天气、轻量问答；训练和食谱等未开放能力会被拒绝 |
| 定时群推送 | `SchedulerManager` / `WebhookComposerAgent` | 原样推送固定正文、追加天气查询结果，或按配置生成企业微信群 markdown 正文 |

## 项目结构

```text
personal_butler_agent/
├── src/
│   ├── main.py                  # FastAPI app、单例 wiring、callback route、scheduler
│   ├── config.py                # .env 配置加载
│   ├── messaging/               # InboundMessage、group_policy、scene dispatch
│   ├── wechat/                  # 智能机器人 URL 回调、加解密、入站落库、response_url 回复
│   ├── scheduler/               # target model/config、webhook client、APScheduler manager
│   ├── cli/                     # 可安装的维护命令
│   ├── agents/
│   │   ├── private_butler/      # 私聊 tool-calling 总控 agent
│   │   ├── group_mention/       # 群聊 @ 受限 agent
│   │   ├── webhook_composer/    # scheduler-only 群 markdown 生成 agent
│   │   ├── summary/             # 文本/群聊摘要
│   │   └── reminder/            # 群 webhook 提醒创建、查看和取消
│   ├── knowledge/               # Stage 2 QA-first 混合知识库检索
│   ├── memory/                  # 对话记忆和摘要压缩
│   ├── models/                  # SQLAlchemy ORM models
│   ├── schemas/                 # AgentResponse 等共享 schema
│   ├── llm/                     # ChatOpenAI/DeepSeek wrapper
│   └── db/                      # async engine/session/base
├── tests/                       # pytest 测试
├── docs/agent/                  # 当前上下文、模式、决策、排障、配置说明
├── config/scheduler_targets.example.json
├── deployment.en.md
├── deployment.md
├── AGENTS.md
├── CLAUDE.md
└── README.md
```

## 快速开始

```bash
uv sync
cp .env.example .env
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

测试：

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

导入本地知识文档：

```bash
uv run butler-ingest-knowledge notes.md --scope-type public --domain qa
```

本地企业微信联调需要公网 HTTPS。可以用 HTTPS 隧道把本地 `127.0.0.1:8000` 暴露给企业微信后台，然后配置：

```text
https://<你的域名>/api/wechat/aibot/callback
```

生产部署详见 [deployment.md](deployment.md)。

## 配置

基础 `.env`：

```env
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite+aiosqlite:///butler.db

WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WECOM_AIBOT_TOKEN=your-callback-token
WECOM_AIBOT_ENCODING_AES_KEY=your-43-char-encoding-aes-key
```

定时群 webhook 推送：

```env
SCHEDULER_TARGETS_FILE=config/scheduler_targets.local.json
```

target JSON 示例：

```json
[
  {
    "name": "cosmic-humor-empire-morning",
    "display_name": "宇宙幽默帝国",
    "cron": "0 9 * * *",
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_WEBHOOK_KEY",
    "mode": "raw",
    "message": "早上好，今天记得看一下今日重点。",
    "weather_query": "今天杭州天气",
    "aliases": ["宇宙幽默帝国"],
    "mention_user_overrides": {},
    "enabled": true
  }
]
```

当前本地配置只有一个目标群：`宇宙幽默帝国`。`name` 是内部稳定标识；`display_name` 是私聊确认和提醒列表里展示给用户看的群名；`mode` 为 `raw` 时原样发送 `message`，为 `compose` 时保留旧的 LLM 生成正文；`weather_query` 仅支持 `raw`，存在时会在到点后查询天气并追加到 `message` 后，一次性推送；`aliases` 用于解析“在宇宙幽默帝国提醒我”这类自然语言目标。

私聊创建群提醒示例：

```text
创建提醒，今天19:10分在宇宙幽默帝国提醒我该健身了
```

确认回复会展示用户可见群名和北京时间，例如：

```text
已创建提醒 #1：健身提醒
目标群：宇宙幽默帝国
提醒对象：@LuZhenDong
下次触发：2026-06-04 19:10（Asia/Shanghai）
```

真实 `.env` 和真实 webhook 地址都不要提交到仓库。

## 消息处理规则

| 消息类型 | 行为 |
|----------|------|
| 私聊文本 | 进入 `PrivateButlerAgent`，由 LLM 决定直接回复或调用工具 |
| 私聊语音 | 使用企业微信内置识别文本后按私聊文本处理；识别为空则忽略 |
| 群聊普通消息 | 保存到 `group_messages`，不回复 |
| 群聊总结/天气/简单问题 | 保存后进入 `GroupMentionAgent` |
| 群聊训练/食谱等私聊能力 | 返回短拒绝，提示私聊处理 |
| 其他消息类型 | 返回暂不支持提示 |

## 开发约定

- 先读 `docs/agent/active-context.md`、`docs/agent/patterns.md` 和相关源码再改代码。
- 新跨场景能力先判断归属：私聊、群聊 @、还是 scheduler composition。
- 新 domain agent 保持 `state.py` + `nodes.py` + `graph.py` + `handle()` 结构。
- 不提交真实 API key、真实 `.env` 或真实群 webhook URL。
