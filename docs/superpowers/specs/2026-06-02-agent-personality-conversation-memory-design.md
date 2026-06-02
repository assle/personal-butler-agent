# Agent Personality & Conversation Memory Design

> 为智能机器人增加对话上下文记忆能力，并为每个 agent 注入个性化人格，解决"没上下文"和"语气机械"两个体验问题。

## Overview

当前系统每次 LLM 调用只传「system prompt + 当前一条消息」，既没有跨轮次记忆，也没有人格温度。本次改造两件事：

1. **对话记忆系统** — 短期 6 轮消息直接塞 prompt + 更早对话压缩成摘要持久化到 SQLite
2. **Agent 人格 prompt** — 每个 agent 注入性格、说话风格、情感基调

两项改动独立但互补，一起落地。

## Scope

### In Scope

- 新增 `conversation_messages` 和 `conversation_summaries` 两张 SQLite 表
- 新增 `src/memory/conversation.py` — `ConversationMemory` 类：读写消息、触发压缩
- 改造 QA、Fitness(today_plan)、Meal 三个 agent 的 `handle()` 方法注入记忆 + 保存交换
- 改造 4 个 agent 的 system prompt（QA / Fitness / Meal / Summary）
- Fitness `log_training` 路径不加记忆（打卡场景单句完成，不需要上下文）
- Summary agent 不加记忆（每次总结独立），但更新 prompt 基调

### Out of Scope

- 跨 user 的记忆共享
- 向量化检索 / RAG
- 多 agent 间记忆协调

## Design

### 1. 数据模型

**conversation_messages**

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| user_id | TEXT NOT NULL | 用户标识 |
| role | TEXT NOT NULL | "user" 或 "assistant" |
| content | TEXT NOT NULL | 消息文本 |
| created_at | TEXT NOT NULL | ISO 时间戳 |

索引：`(user_id, created_at)`

**conversation_summaries**

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 自增 |
| user_id | TEXT NOT NULL UNIQUE | 用户标识，每个用户一行 |
| summary_text | TEXT NOT NULL | 压缩后的摘要文本 |
| last_summarized_at | TEXT NOT NULL | 最后一次触发压缩的时间 |

### 2. ConversationMemory 模块

新增 `src/memory/conversation.py`，对外两个方法：

**`get_context(user_id, db) → (summary, recent_messages)`**
- 查 `conversation_summaries` 取摘要（可能为 None）
- 查 `conversation_messages` 取最近 12 条（6 轮），按时间升序
- 返回摘要字符串 + 消息列表

**`save_exchange(user_id, user_msg, assistant_msg, db)`**
- 写入两条 `conversation_messages`（一条 user、一条 assistant）
- 如果该用户总消息数超过 24 条（12 轮），触发 `_compress()`

**`_compress(user_id, db)`**
- 取最早 12 条消息 + 现有摘要文本 → 调 LLM 生成一句新的累积摘要
- 写入 `conversation_summaries`（upsert）
- 删除已压缩的 6 条消息（保留最近 12 条）

不引入新 LLM 调用路径——复用现有 `LLMClient.chat()`，传一个轻量级压缩 prompt。

### 3. Agent handle() 改造

三个 agent 的 `handle()` 流程变为：

```python
async def handle(self, intent, message, user_id, db):
    memory = ConversationMemory(self._llm)
    summary, recent = await memory.get_context(user_id, db)

    initial_state = {
        "intent": intent,
        "message": message,
        "user_id": user_id,
        "conversation_summary": summary,
        "recent_messages": recent,
    }
    config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
    result = await self._graph.ainvoke(initial_state, config)

    reply = result.get("reply", "")
    await memory.save_exchange(user_id, message, reply, db)
    return AgentResponse(reply=reply, data=result.get("data"))
```

节点函数中，各 agent 的 generate 节点把 `conversation_summary` 和 `recent_messages` 拼进 messages 数组：

```python
messages = [{"role": "system", "content": SYSTEM_PROMPT.format(...)}]

# 拼接摘要
if state.get("conversation_summary"):
    messages.append({
        "role": "system",
        "content": f"这是你们之前对话的摘要：{state['conversation_summary']}",
    })

# 拼接近期消息
for msg in state.get("recent_messages", []):
    messages.append(msg)

# 当前用户消息
messages.append({"role": "user", "content": state["message"]})
```

### 4. Agent 人格 Prompt

各 agent 的 system prompt 替换为以下内容。

#### QA Agent — "小管家"

```
你是"小管家"，用户的私人 AI 助理，陪伴用户日常生活。

性格底色：细心、温暖、偶尔带点小幽默但不油腻。

说话方式：
- 像认识很久的朋友，自然口语化，不要客服腔和机器人感
- 用户偏好中有名字的话，偶尔叫名字显得亲近
- 关心用户的感受和状态，不只是一问一答
- 适当用 emoji 传递情绪，不泛滥
- 不知道就说不知道，不要编

回复长度：日常聊天 2-4 句即可，深入问题可以详细展开。

用户档案（来自系统记录）：
{preferences}

{conversation_context}
```

#### Fitness Agent — "铁块教练"

```
你是"铁块教练"，用户的私人健身教练。

性格底色：热血、直接、有股子"再来一组"的劲头，但说到安全动作时就切回认真模式。

说话方式：
- 用老铁/兄弟称呼，别太频繁
- 鼓励要有，但不尬吹——用户划水了也要点出来
- 讲动作细节时切换成简洁清晰的专业口吻
- 可以加 💪 🔥 这类 emoji

回复长度：训练建议 3-5 句，打卡确认 1-2 句。

用户档案：
- 近期训练历史：{training_history}
- 偏好：{preferences}
- 对话上下文：{conversation_context}
```

#### Meal Agent — "小厨"

```
你是"小厨"，用户的私人营养顾问。

性格底色：细心、讲究、对食物有热情，聊到好吃的会兴奋但不过分。

说话方式：
- 讲营养知识时像科普博主：易懂、有趣、不吓人
- 推荐食谱时带一点画面感（"鸡胸肉煎到两面金黄..."）
- 理解用户的饮食偏好和禁忌，不强行说教
- 偶尔用 🍳 🥗 这类食物 emoji

回复长度：一日三餐推荐 5-8 句，简单问答 2-3 句。

用户档案：
- 偏好：{preferences}
- 近期训练状况：{training_context}
- 对话上下文：{conversation_context}
```

#### Summary Agent — "会议纪要员"

保持当前简洁结构，加一句风格指引：

```
你是群聊总结助手。风格：客观、条理清晰、抓住重点，不添油加醋。
用以下格式总结群聊记录：
...
```

### 5. 压缩 Prompt

轻量级，用于把旧消息 + 旧摘要压缩成一句话：

```
你是对话摘要器。把以下对话历史和之前的摘要压缩成一句简短摘要（不超过80字），
保留关键事实和偏好信息。

之前的摘要：{existing_summary}

最新对话：
{old_messages}

只输出摘要文本，不要多余的话。
```

## Memory Agent 覆盖表

| Agent | Intent | 加记忆 | 改 prompt |
|-------|--------|--------|-----------|
| QA | qa, unknown | 是 | 是 |
| Fitness | today_plan | 是 | 是 |
| Fitness | log_training | 否 | 是（共用 prompt） |
| Meal | make_meal_plan | 是 | 是 |
| Summary | summarize_text | 否 | 是 |
| Summary | summarize_group | 否 | 否（群聊场景不需要人格） |

## Error Handling

- `get_context()` 异常 → 返回空摘要 + 空消息列表，不阻断对话
- `save_exchange()` 异常 → 记录日志，不阻断回复
- 压缩失败 → 跳过本轮压缩，等下次触发，不影响消息写入
- `conversation_context` 为空时 → prompt 中 `{conversation_context}` 替换为 "（暂无历史对话）"

## Testing

- 现有 88 个测试应全部通过（回归验证）
- 建议新增：
  - `conversation_messages` 和 `conversation_summaries` ORM 的 CRUD 测试
  - `ConversationMemory.get_context` 正常返回 + 空表场景
  - `ConversationMemory.save_exchange` 写入 + 触发压缩
  - agent `handle()` 注入记忆 + 保存交换的集成测试（mock LLM）
  - 各 agent prompt 包含新占位符的格式化测试
