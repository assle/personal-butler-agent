# Group Chat Summarization — Implementation Plan

**Goal:** When a user @mentions the bot in a WeChat Work group chat with "总结一下群消息", the bot retrieves recent group messages, generates a structured summary via LLM, and replies in the group chat.

**Precondition:** WeChat Work admin console → App Settings → Receive Messages → **Enable "Group Chat Messages"**. Without this, the self-built app only receives @mention messages and cannot passively collect group chat history.

**Architecture:**

```
Group Chat Messages (all) → WeChat Work → POST /api/wechat/callback
                                                  ↓
                                         Parse ChatId / ChatType
                                                  ↓
                                    ┌─────────────┴──────────────┐
                                    ↓                            ↓
                           chat_type == "group"          chat_type == "single"
                           ALWAYS save to DB             (existing flow)
                                    ↓
                          ┌─────────┴─────────┐
                          ↓                   ↓
                   @bot + "总结"       Not a trigger
                   keyword?           Return empty 200
                          ↓              (no reply)
                   Fetch last N msgs
                   from DB for ChatId
                          ↓
                   LLM summarization
                          ↓
                   Encrypted reply
                   → Group Chat
```

---

## Task 1: Update message parsing to detect group chat context

**Files:**
- Modify: `src/wechat/messages.py`
- Modify: `tests/test_wechat_messages.py`

**Background:** WeChat Work group chat callbacks include additional fields in the inner XML. We need to detect whether a message comes from a private chat (`single`) or a group chat (`group`), and capture the group chat ID.

The group chat inner XML looks like:

```xml
<xml>
  <ToUserName><![CDATA[corpid]]></ToUserName>
  <FromUserName><![CDATA[user_openid]]></FromUserName>
  <CreateTime>1780217822</CreateTime>
  <MsgType><![CDATA[text]]></MsgType>
  <Content><![CDATA[@botname 总结一下群消息]]></Content>
  <MsgId>1234567890</MsgId>
  <AgentId>1000001</AgentId>
</xml>
```

Note: The exact field names for ChatId/ChatType in WeChat Work self-built app callbacks need to be verified against actual callback data. The plan accounts for both documented field names.

- [ ] **Step 1: Add chat_id and chat_type fields to InnerMessage**

```python
# src/wechat/messages.py

@dataclass
class InnerMessage:
    """解密后的内层明文消息"""
    to_user_name: str
    from_user_name: str
    create_time: int
    msg_type: str
    content: str
    msg_id: str
    chat_id: str = ""       # 群聊 ID，私聊时为空
    chat_type: str = "single"  # "single" 或 "group"
```

- [ ] **Step 2: Update parse_inner_xml to extract chat fields**

```python
def parse_inner_xml(decrypted: str) -> InnerMessage:
    root = ElementTree.fromstring(decrypted)
    return InnerMessage(
        to_user_name=_get_cdata(root, "ToUserName"),
        from_user_name=_get_cdata(root, "FromUserName"),
        create_time=int(_get_cdata(root, "CreateTime")),
        msg_type=_get_cdata(root, "MsgType"),
        content=_get_cdata(root, "Content"),
        msg_id=_get_cdata(root, "MsgId"),
        chat_id=_get_cdata(root, "ChatId"),
        chat_type=_get_cdata(root, "ChatType") or "single",
    )
```

- [ ] **Step 3: Add tests for group chat XML parsing**

- [ ] **Step 4: Run tests and commit**

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_wechat_messages.py -v
git add src/wechat/messages.py tests/test_wechat_messages.py
git commit -m "feat: add ChatId/ChatType parsing to WeChat inner message"
```

---

## Task 2: Create group message storage model

**Files:**
- Create: `src/models/group_message.py`
- Modify: `src/db/base.py` (register model)
- Create: `tests/test_group_message_model.py`

- [ ] **Step 1: Create GroupMessage ORM model**

```python
# src/models/group_message.py
"""企业微信群聊消息持久化模型"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from src.db.base import Base


class GroupMessage(Base):
    __tablename__ = "group_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(256), nullable=False, index=True)
    user_id = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    create_time = Column(Integer, nullable=False)
    stored_at = Column(DateTime, default=datetime.utcnow)

    @classmethod
    async def save(cls, db, chat_id, user_id, content, create_time):
        msg = cls(chat_id=chat_id, user_id=user_id,
                   content=content, create_time=create_time)
        db.add(msg)
        await db.flush()
        return msg

    @classmethod
    async def get_recent(cls, db, chat_id, limit=50):
        """获取群聊最近 N 条消息"""
        from sqlalchemy import select, desc
        stmt = (select(cls)
                .where(cls.chat_id == chat_id)
                .order_by(desc(cls.create_time))
                .limit(limit))
        result = await db.execute(stmt)
        return list(reversed(result.scalars().all()))

    @classmethod
    async def cleanup(cls, db, chat_id, keep=200):
        """每个群聊只保留最近 N 条消息"""
        from sqlalchemy import select, delete, desc
        subq = (select(cls.id)
                .where(cls.chat_id == chat_id)
                .order_by(desc(cls.create_time))
                .offset(keep))
        stmt = delete(cls).where(
            cls.chat_id == chat_id,
            cls.id.in_(subq)
        )
        await db.execute(stmt)
        await db.flush()
```

- [ ] **Step 2: Register model in Base**

```python
# src/db/base.py — add import
from src.models.group_message import GroupMessage  # noqa: F401
```

- [ ] **Step 3: Write model tests and commit**

---

## Task 3: Save group messages passively in the callback

**Files:**
- Modify: `src/wechat/router.py`
- Modify: `tests/test_wechat_router.py`

**Key design decision:** When a message comes from a group chat, we ALWAYS save it to DB. If it's a trigger message (@bot + summarize keyword), we also generate a summary reply. If it's a normal group message, we return an empty 200 (no reply text in the group).

- [ ] **Step 1: Add message saving logic**

In `receive_message`, after parsing the inner message and before intent routing:

```python
# 群聊消息：始终保存到数据库（静默收集）
if inner.chat_type == "group" and inner.chat_id:
    from src.models.group_message import GroupMessage
    await GroupMessage.save(
        db, inner.chat_id, inner.from_user_name,
        inner.content, inner.create_time
    )
    await GroupMessage.cleanup(db, inner.chat_id, keep=200)
```

- [ ] **Step 2: Handle non-trigger group messages (silent return)**

After saving, if the message is from a group chat but does NOT contain the summarize trigger, return an empty 200 to avoid spamming the group.

```python
# 群聊消息：仅 @机器人 + "总结" 关键词时触发总结
if inner.chat_type == "group":
    if not _is_summarize_trigger(inner.content):
        return Response(content="success")  # 静默收集，不回复
    # 继续走到总结逻辑...
```

- [ ] **Step 3: Implement trigger detection**

```python
def _is_summarize_trigger(content: str) -> bool:
    """检测消息是否触发群聊总结（@bot + 总结关键词）"""
    keywords = ["总结", "摘要", "概括", "汇总"]
    return any(kw in content for kw in keywords)
```

Note: WeChat Work's @mention in group chat shows as `@botname` in the content. The keyword check on the raw content is sufficient — no need to strip the @mention prefix since it doesn't interfere with keyword matching.

- [ ] **Step 4: Add tests and commit**

---

## Task 4: Implement group chat summarization node

**Files:**
- Modify: `src/agents/summary/nodes.py` (add group summarization node)
- Modify: `src/agents/summary/graph.py` (add group summary path)
- Modify: `tests/test_summary.py`

- [ ] **Step 1: Add group summarize node**

```python
# src/agents/summary/nodes.py

async def summarize_group_messages(state: dict) -> dict:
    """从数据库获取群聊最近消息，调用 LLM 生成结构化摘要

    参数:
        state: 包含 chat_id, user_id 的当前状态

    返回:
        dict: {"reply": LLM 生成的结构化摘要} 或 {"error": 错误信息}
    """
    config = get_config()
    llm = config["configurable"]["llm"]
    db = config["configurable"]["db"]
    chat_id = state.get("chat_id", "")

    # 获取最近 50 条消息
    from src.models.group_message import GroupMessage
    messages = await GroupMessage.get_recent(db, chat_id, limit=50)

    if not messages:
        return {"reply": "暂无最近的群聊消息可供总结。"}

    # 构建对话记录文本
    transcript_lines = []
    for msg in messages:
        transcript_lines.append(f"[{msg.user_id}]: {msg.content}")
    transcript = "\n".join(transcript_lines)

    # 调用 LLM 总结
    try:
        reply = await llm.chat(
            messages=[
                {"role": "system", "content": GROUP_SUMMARY_PROMPT},
                {"role": "user", "content": f"以下是最新的群聊记录，请总结：\n\n{transcript}"},
            ],
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


GROUP_SUMMARY_PROMPT = """你是群聊总结助手。用以下格式总结群聊记录：

讨论主题：<一句话概括>
关键结论：
  - <结论1>
  - <结论2>
待办事项：
  - @<负责人> <事项>
决策：<已做出的决策，无则写"无">
未解决的问题：<有分歧或未解决的问题>

只返回上述格式，不要有其他说明文字。不要编造不存在的信息。"""
```

- [ ] **Step 2: Update SummaryAgent to add group summarization path**

In `graph.py`, add a route after message classification:

```python
def _route_after_classify(state: dict) -> str:
    chat_type = state.get("chat_type", "single")
    if chat_type == "group":
        return "summarize_group"
    return "summarize_text"

# In _build_graph:
builder.add_conditional_edges("classify", _route_after_classify, {
    "summarize_group": "summarize_group",
    "summarize_text": "generate_summary",
})
```

- [ ] **Step 3: Handle state injection in router**

In the router, when trigger is detected, inject `chat_id` into the agent state:

```python
result = await agent.handle(
    "summarize_group", inner.content, inner.from_user, db,
    extra_state={"chat_id": inner.chat_id, "chat_type": "group"}
)
```

Note: This requires updating the `handle` method signature on affected agents to accept optional `extra_state`. Alternatively, encode `chat_id` in the intent string or pass it via a different mechanism.

- [ ] **Step 4: Add tests and commit**

---

## Task 5: End-to-end integration and manual verification

- [ ] **Step 1: Configure WeChat Work admin**

1. Open WeChat Work admin console → Apps → Your self-built app → Receive Messages
2. Enable "Group Chat Messages" (接收群聊消息)
3. Add the bot to a test group chat

- [ ] **Step 2: Deploy and test**

1. Deploy updated code to server
2. Send a few normal messages in the test group (to build up history)
3. @bot with "总结一下群消息"
4. Verify the bot replies with a structured summary of the previous messages

- [ ] **Step 3: Verify silent collection**

1. Send normal group messages (without @mentioning the bot)
2. Check server logs — messages are stored but no reply is sent to the group
3. Check DB — group_messages table has the saved messages

---

## Files Changed Summary

| File | Action | Purpose |
|------|--------|---------|
| `src/wechat/messages.py` | Modify | Add chat_id/chat_type to InnerMessage |
| `src/models/group_message.py` | Create | GroupMessage ORM model |
| `src/db/base.py` | Modify | Register GroupMessage model |
| `src/wechat/router.py` | Modify | Save group msgs, trigger detection, silent return |
| `src/agents/summary/nodes.py` | Modify | Add summarize_group_messages node |
| `src/agents/summary/graph.py` | Modify | Add group summary path to StateGraph |
| `tests/test_wechat_messages.py` | Modify | Group chat XML parsing tests |
| `tests/test_group_message_model.py` | Create | GroupMessage CRUD tests |
| `tests/test_wechat_router.py` | Modify | Group message handling tests |
| `tests/test_summary.py` | Modify | Group summarization tests |

## Key Design Decisions

1. **Passive collection + trigger-based reply:** All group messages are saved silently. Only @mention + summarize keyword triggers a reply. This avoids spamming the group.

2. **Per-group message cap at 200:** Each group chat keeps the last 200 messages. Old messages are cleaned up on each insert. This prevents unbounded DB growth.

3. **Reuse existing SummaryAgent:** Instead of creating a new agent, we add a `summarize_group` branch to the existing SummaryAgent StateGraph. The graph routes to different nodes based on chat_type.

4. **@mention detection via keyword matching:** We don't need to parse the @mention syntax. The summarize keywords ("总结" etc.) in the message content are sufficient to detect the trigger, since normal group messages won't contain these words as standalone commands.
