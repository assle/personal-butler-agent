# Scenario Agent Refactor Design

> 将 Personal Butler Agent 从“一个总控 ButlerAgent + 全局 intent 路由”的混合结构，重构为按入口场景拆分的 agent 架构：私聊、群聊 @、群 webhook 定时推送各自拥有独立边界。

## Overview

当前项目已经从早期 `IntentRouter -> AgentRegistry -> domain agent` 迁移到 `ButlerAgent` tool-calling 主入口，但入口边界仍然混在一起：

- 私聊需要完整的小管家能力，包括陪伴式聊天、训练、食谱、知识库和联网搜索。
- 群聊 @ 机器人只需要低打扰的任务型能力，包括群聊总结、天气查询占位和简单问答。
- 群 webhook 定时推送不是聊天入口，只需要根据配置生成最终要推送的 markdown 正文。

继续让一个 `ButlerAgent` 同时理解这些场景，会让 prompt、工具列表、触发规则和测试都变得模糊。本设计选择拆分为三个场景 agent，并删除不再使用的 debug API、WebSocket 兼容入口和全局 intent 路由。

目标是让代码结构和产品边界一致：先确定入口场景，再进入对应 agent。业务能力仍保留现有领域 agent 的可复用逻辑，但不再把所有场景压进同一个总控 agent。

## Scope

### In Scope

- 新增 `PrivateButlerAgent`，作为私聊智能机器人入口。
- 新增 `GroupMentionAgent`，作为群聊 @ 智能机器人入口。
- 新增 `WebhookComposerAgent`，作为 APScheduler 群 webhook 推送内容生成入口。
- 新增 `src/messaging/`，统一表示入站消息、群消息策略和场景分发。
- 删除 `POST /api/debug/message` 及本地 debug/dev message API。
- 删除 WebSocket 智能机器人兼容代码。
- 删除全局 `src/intent/` 路由模块，将意图判断收窄到具体场景。
- 迁移并删除旧 `src/agents/butler/`。
- 调整 `src/main.py`，只注册企微 URL callback 路由，并配置 scheduler webhook。
- 调整 scheduler，使定时 webhook 只调用 `WebhookComposerAgent`。
- 更新项目文档和测试，移除旧架构保护，增加场景边界验证。

### Out of Scope

- 接入真实天气 API。第一阶段只识别天气查询并返回功能待配置。
- 新增 debug/dev HTTP 消息入口。
- 恢复或保留 WebSocket 长连接入站。
- 让群聊普通消息触发 LLM 回复。
- 重写 Fitness、Meal、Summary、QA 领域 agent 的内部业务逻辑。
- 引入队列、Redis、Celery 或多进程任务系统。

## Architecture

### 1. Scene-First Boundary

系统先识别消息入口场景，再进入对应 agent：

```text
WeChat Work URL callback
├── chat_type=single -> PrivateButlerAgent
└── chat_type=group  -> group_policy -> GroupMentionAgent or no reply

APScheduler webhook target
└── WebhookComposerAgent -> WebhookPushClient
```

不再有一个全局 `IntentRouter` 试图覆盖所有消息。场景本身就是第一层路由。

### 2. Agent Roles

#### PrivateButlerAgent

私聊入口专用，负责完整小管家能力。

允许能力：

- 陪伴式聊天和一般问答。
- 训练记录和今日训练计划。
- 食谱和饮食计划。
- 文本总结。
- 本地知识库检索。
- 联网搜索。

实现方式：

- 从当前 `src/agents/butler/` 迁移而来。
- 继续使用 LangGraph tool-calling loop。
- 工具列表可以包含训练、食谱、摘要、知识库、联网搜索等完整私聊能力。
- prompt 强调更自然、更有人味的私聊风格。

#### GroupMentionAgent

群聊 @ 机器人入口专用，负责低打扰任务型回复。

允许能力：

- 群聊总结。
- 天气查询占位。
- 简单问答。

禁止能力：

- 训练记录。
- 训练计划。
- 食谱制定。
- 陪伴式长对话。
- 私人知识库访问，除非未来显式增加群可见授权。

实现方式：

- 不复用 `PrivateButlerAgent` 的完整工具列表。
- 使用场景内分类器判断 `summarize_group`、`weather_placeholder`、`simple_qa`、`unsupported`。
- 关键词规则优先，LLM 仅作为群聊分类兜底。
- 天气查询返回固定占位回复，例如“天气功能还没有接入数据源，配置完成后我就能查询。”
- 训练和食谱请求返回短拒绝，例如“群聊里我只处理总结、天气和简单问答，训练和食谱请私聊我。”

#### WebhookComposerAgent

群 webhook 定时推送专用，不是聊天 agent。

允许能力：

- 根据 scheduler target 的 `message` 生成最终群 markdown 正文。

禁止能力：

- 不调用训练、食谱、问答、天气、群总结工具。
- 不回答“我没有权限发送”。
- 不输出手动操作步骤。

实现方式：

- 使用简单 LangGraph 或直接 agent wrapper 均可，第一版保持 agent 接口一致。
- prompt 明确说明系统会负责发送，模型只生成正文。
- scheduler 调用完成后由 `WebhookPushClient` 发送到企业微信群 webhook。

## Proposed File Structure

```text
src/agents/private_butler/
├── __init__.py
├── graph.py
├── nodes.py
├── prompts.py
├── state.py
└── tools.py

src/agents/group_mention/
├── __init__.py
├── classifier.py
├── graph.py
├── nodes.py
├── prompts.py
└── state.py

src/agents/webhook_composer/
├── __init__.py
├── graph.py
├── nodes.py
├── prompts.py
└── state.py

src/messaging/
├── __init__.py
├── dispatch.py
├── group_policy.py
└── inbound.py
```

### Files To Remove

```text
src/agents/butler/
src/intent/
src/router/debug.py
src/router/
src/wechat/message_handler.py
src/wechat/ws_client.py
tests/test_api.py
tests/test_intent.py
tests/test_message_handler.py
tests/test_ws_client.py
```

The exact test deletion list can expand during implementation if additional tests only protect removed debug, WS, or global intent behavior.

### Files To Keep And Slim Down

```text
src/wechat/callback_router.py
src/wechat/callback_handler.py
src/wechat/callback_crypto.py
src/wechat/callback_inbox.py
```

`callback_router.py` remains responsible for HTTP request parsing, signature validation, decryption, inbound idempotency, and background processing.

`callback_handler.py` remains part of the URL callback path, but becomes thin:

```text
parsed callback msg
-> InboundMessage.from_wecom_callback()
-> dispatch_message()
-> response_url reply if dispatch produced reply
```

It should not own group trigger rules, group message persistence, or agent selection.

## Message Model

`src/messaging/inbound.py` defines a normalized message object:

```python
@dataclass(frozen=True)
class InboundMessage:
    source: str
    msg_id: str
    msg_type: str
    user_id: str
    content: str
    chat_type: str
    chat_id: str | None
    response_url: str | None
    raw: dict
```

`source` examples:

- `wecom_callback`
- `scheduler_webhook`

`chat_type` values:

- `single`
- `group`

The normalized message keeps WeChat-specific parsing out of agent code.

## Group Policy

`src/messaging/group_policy.py` owns group-message behavior.

Rules:

1. Every text or recognized voice group message with `chat_id` is saved to `group_messages`.
2. After saving, old group messages are cleaned up using the existing retention behavior.
3. Non-trigger group messages do not call LLM and do not reply.
4. Triggered group messages enter `GroupMentionAgent`.

Trigger definition for first implementation:

- Explicit summary keywords: `总结`、`摘要`、`概括`、`汇总`.
- Weather keywords: `天气`、`气温`、`下雨`、`降雨`.
- Simple direct question when the platform has delivered the message as a robot callback.

If the WeChat callback payload includes an explicit mention marker in the future, `group_policy` should use it. Until then, callback delivery plus content rules define whether to reply.

## Message Flows

### Private Chat

```text
POST /api/wechat/aibot/callback
-> callback_router verifies/decrypts/records inbound message
-> process_recorded_message()
-> callback_handler builds InboundMessage
-> dispatch_message(chat_type=single)
-> PrivateButlerAgent.handle()
-> ResponseUrlReplyClient.send_reply()
```

Private chat does not use keyword intent routing. The private agent decides directly through LLM/tool-calling.

### Group Mention

```text
POST /api/wechat/aibot/callback
-> callback_router verifies/decrypts/records inbound message
-> process_recorded_message()
-> callback_handler builds InboundMessage
-> dispatch_message(chat_type=group)
-> group_policy saves group message
-> group_policy decides reply/no reply
-> GroupMentionAgent.handle()
-> ResponseUrlReplyClient.send_reply()
```

Group non-trigger messages stop after persistence and cleanup.

### Scheduled Webhook Push

```text
APScheduler job fires
-> SchedulerManager loads target config
-> WebhookComposerAgent.handle()
-> WebhookPushClient.send_markdown()
-> commit on success, rollback on failure
```

Scheduler does not auto-route intent and does not call `PrivateButlerAgent`.

## Error Handling

- Callback route keeps the current reliable pattern: receive, verify, persist inbound message, return success quickly, process in background.
- Callback processing marks the inbound message `processing`, then `processed` or `failed`.
- If `response_url` sending fails, processing records failure rather than retrying inside the HTTP callback.
- `PrivateButlerAgent` failure replies with a private-chat friendly service error.
- `GroupMentionAgent` failure replies with a short group-safe service error.
- `WebhookComposerAgent` failure logs and rolls back; it does not push partial content.
- Weather queries always return a stable placeholder until a weather data source is configured.

## Testing Strategy

Tests should protect the new scenario boundaries rather than old debug or global intent behavior.

### Keep And Adapt

- Callback router tests: verify signature/decryption/inbound persistence/background processing.
- Callback handler tests: verify normalized dispatch and response URL behavior.
- Scheduler tests: verify webhook targets call `WebhookComposerAgent`, not generic intent routing.
- Summary tests: keep group summary behavior through `SummaryAgent`.
- Butler tool tests: migrate to private-butler tool tests where private chat still needs those tools.

### Add

- `messaging.inbound` conversion from WeChat callback payload.
- `messaging.group_policy` saves group messages, suppresses non-trigger replies, and triggers allowed group requests.
- `messaging.dispatch` sends single chat to `PrivateButlerAgent` and group chat to `GroupMentionAgent`.
- `GroupMentionAgent` allows group summary, weather placeholder, and simple QA.
- `GroupMentionAgent` rejects training and meal requests.
- `WebhookComposerAgent` produces markdown body and does not call private/chat tools.

### Delete

- Debug API tests.
- Global intent router tests.
- WebSocket handler/client tests.

## Documentation Updates

- `docs/agent/active-context.md`: describe current entry points and the three scenario agents.
- `docs/agent/patterns.md`: add scene-first dispatch, group policy, and webhook composer patterns.
- `docs/agent/decisions.md`: add ADR for deleting debug API, WS compatibility, global intent routing, and old all-purpose ButlerAgent.
- `docs/agent/config-variables.md`: keep URL callback and scheduler webhook config, remove stale debug/WS guidance.
- `docs/agent/troubleshooting.md`: remove or archive WS troubleshooting, retain URL callback and webhook diagnostics.
- `AGENTS.md` and `CLAUDE.md`: update only if root project guidance changes, and keep them byte-for-byte identical.

## Migration Notes

Implementation should proceed in stages:

1. Introduce scenario agent packages while keeping old code temporarily available.
2. Add `src/messaging/` and move group message policy out of callback/debug handlers.
3. Wire URL callback to dispatch through `PrivateButlerAgent` and `GroupMentionAgent`.
4. Wire scheduler to `WebhookComposerAgent`.
5. Remove debug API, WebSocket code, global intent routing, and old `src/agents/butler/`.
6. Update tests and docs to match the new architecture.

This staging avoids a half-migrated state where old debug or intent tests keep pulling the architecture backward.

## Success Criteria

- There is no `POST /api/debug/message` route and no debug/dev message API.
- There is no WebSocket intelligent robot runtime path.
- There is no global `src/intent/` module.
- There is no old `src/agents/butler/` package after migration.
- URL callback private messages enter `PrivateButlerAgent`.
- URL callback group messages are saved, non-trigger messages do not reply, and allowed trigger messages enter `GroupMentionAgent`.
- Group mention requests for training or meal planning are rejected in group context.
- Weather queries in group context return a configured placeholder.
- Scheduler webhook targets call `WebhookComposerAgent` only.
- Existing domain agents remain reusable behind the new scenario agents.
- Relevant tests pass with `DEEPSEEK_API_KEY=test uv run pytest -q`.
