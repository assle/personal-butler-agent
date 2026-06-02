# 企业微信智能机器人长连接模式设计

> 状态：已确认 | 2026-06-02

## 背景

当前智能机器人使用 HTTP 回调模式，只能被动回复消息，无法主动推送。要实现 APScheduler 定时推送，需要切换到长连接模式（WebSocket），该模式下支持 `aibot_send_msg` 主动推送。

## 目标

- 智能机器人从回调模式切换到长连接模式（WebSocket）
- APScheduler 定时触发 agent (LLM) 管线 → WebSocket 主动推送
- 推送目标、时间、触发消息均通过 `.env` 可配置
- Agent 管线零改动

## 架构

```
FastAPI 进程
├── HTTP 路由 (debug 等，不变)
├── WebSocket 客户端 (新增) ── 企微服务器
│   ├── 接收消息 → agent 管线 → send_reply
│   └── push_message ← scheduler
└── APScheduler (新增)
    └── 到点触发 → agent 管线 → ws.push_message
```

## 配置

新增 5 个配置项，移除 3 个旧配置：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `WECOM_AIBOT_BOT_ID` | str | "" | 智能机器人 BotID |
| `WECOM_AIBOT_SECRET` | str | "" | 智能机器人 Secret |
| `SCHEDULER_CRON` | str | "0 9 * * *" | cron 表达式 |
| `SCHEDULER_TARGET_TYPE` | str | "single" | single / group |
| `SCHEDULER_TARGET_ID` | str | "" | userid 或 chatid |
| `SCHEDULER_MESSAGE` | str | "今日训练建议" | 发给 agent 的触发消息 |
| `SCHEDULER_INTENT` | str | "today_plan" | agent intent |

移除：
- `WECHAT_ROBOT_TOKEN`（长连接不需要加解密）
- `WECHAT_ROBOT_ENCODING_AES_KEY`（同上）
- `WECHAT_WEBHOOK_URL`（群机器人 webhook，功能被替代）

保留自建应用配置（`WECHAT_CORP_ID` 等），那是另一套独立系统。

## 模块设计

### 1. WebSocket 客户端 (`src/wechat/ws_client.py`)

类 `WeComWSClient`：

- 连接 `wss://openws.work.weixin.qq.com`
- 发送 `aibot_subscribe` 认证（BotID + Secret）
- 循环接收消息帧，分发处理
- 暴露 `send_reply(content, msgid)` — 回复消息
- 暴露 `push_message(target_type, target_id, msgtype, content)` — 主动推送
- 自动重连：指数退避 1s → 2s → 4s → 最大 30s
- 心跳：每 30s ping，超时触发重连
- 作为独立 asyncio Task 运行

消息指令：

| 指令 | 方向 | 用途 |
|------|------|------|
| `aibot_subscribe` | 发出 | 认证订阅 |
| `aibot_msg_callback` | 收到 | 用户消息回调 |
| `aibot_respond_msg` | 发出 | 回复消息 |
| `aibot_send_msg` | 发出 | 主动推送 |

### 2. 消息处理 (`src/wechat/ws_client.py` 内回调)

收到 `aibot_msg_callback` 后：

1. 解析 userid、content、chatid、chattype
2. 群聊消息保存到 DB（同现在 `robot_router.py` 逻辑）
3. 触发词检测 → summarize_group
4. 私聊消息 → intent_router → agent 处理 → send_reply

与当前 `robot_router.py` 的处理逻辑一致，只是入口从 HTTP 变成 WebSocket 回调。

### 3. 调度器 (`src/scheduler/__init__.py`)

类 `SchedulerManager`：

- 单例，管理 APScheduler 生命周期
- 注册一条 job，cron 从配置读取
- job 函数：取 scheduler_message → agent.handle() → ws.push_message()
- 启动/停止钩子

### 4. Lifespan 集成 (`src/main.py`)

```python
async def lifespan(app):
    # 建表（不变）
    ...
    # 启动 WS 连接
    # 启动 scheduler
    yield
    # 停止 scheduler
    # 关闭 WS
    # 释放引擎
```

### 5. 配置层 (`src/config.py`)

新增长连接和调度器字段，移除 Webhook 和 robot 加解密字段。

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/wechat/ws_client.py` | 新增 | WebSocket 长连接客户端 + 消息处理回调 |
| `src/scheduler/__init__.py` | 新增 | APScheduler 管理器 |
| `src/config.py` | 修改 | 新增/移除配置项 |
| `src/main.py` | 修改 | lifespan 启动 WS 和 scheduler |
| `src/wechat/robot_router.py` | 删除 | 被 ws_client 替代 |
| `src/wechat/webhook.py` | 删除 | 群机器人 webhook，不再需要 |
| `src/wechat/__init__.py` | 修改 | 更新导出 |
| `tests/test_wechat_robot_router.py` | 删除 | 路由已移除 |
| `tests/test_wechat_webhook.py` | 删除 | 不再需要 |
| `tests/test_ws_client.py` | 新增 | WS 客户端测试 |
| `tests/test_scheduler.py` | 新增 | 调度器测试 |
| `docs/agent/config-variables.md` | 修改 | 更新配置文档 |
| `docs/agent/decisions.md` | 修改 | 添加 ADR-011 |
| `docs/agent/upgrade-roadmap.md` | 修改 | 更新升级路线图 |

## 风险与限制

- 长连接需要维护 WebSocket 连接，断线自动重连已设计在内
- 频率限制：30 条/分钟，1000 条/小时（回复+推送共享）
- 用户/群聊需先给机器人发过消息才能接收主动推送（企业微信限制）
