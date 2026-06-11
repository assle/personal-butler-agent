# 翻译功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在私聊和群聊中通过 LLM 将文本翻译成任意目标语言。

**Architecture:** 新增 `translate_text` 工具函数，在 PrivateButlerAgent 中作为 tool 注册，在 GroupMentionAgent 中作为关键词触发节点。不创建新 agent 或数据库表。

**Tech Stack:** Python 3.13+, LangChain tool decorator, 复用现有 LLMClient

---

### Task 1: 创建共享翻译函数

**Files:**
- Create: `src/agents/translate.py`

- [ ] **Step 1: 创建文件**

```python
"""
翻译工具函数
调用 LLM 将文本翻译成任意目标语言，供私聊 tool 和群聊节点共用。

Workflow:
  私聊: PrivateButlerAgent tool → translate_text()
  群聊: GroupMentionAgent translate_node → translate_text()
"""
from __future__ import annotations


TRANSLATE_PROMPT = """你是翻译助手。把用户输入翻译成{target_lang}，只返回译文，不要解释，不要添加任何额外内容。"""


async def translate_text(text: str, target_lang: str, llm) -> str:
    """调用 LLM 翻译文本到目标语言

    参数:
        text: 待翻译的文本
        target_lang: 目标语言描述，例如"英文"、"日文"、"法文"
        llm: LLMClient 实例

    返回:
        str: 翻译后的文本
    """
    result = await llm.chat(
        messages=[
            {"role": "system", "content": TRANSLATE_PROMPT.format(target_lang=target_lang)},
            {"role": "user", "content": text},
        ],
    )
    return result.strip()
```

- [ ] **Step 2: 提交**

```bash
git add src/agents/translate.py
git commit -m "feat: add translate_text helper function"
```

---

### Task 2: 私聊集成 — PrivateButlerAgent translate tool

**Files:**
- Modify: `src/agents/private_butler/tools.py`

- [ ] **Step 1: 在 tools.py 中新增 translate tool**

在文件顶部 import 区新增：

```python
from src.agents.translate import translate_text
```

在 `create_private_butler_tools` 函数内，`cancel_reminder` tool 定义之后，新增 `translate` tool：

```python
@tool
async def translate(message: str) -> str:
    """将文本翻译成用户指定的目标语言

    参数:
        message: 用户的完整翻译请求，应包含目标语言和待翻译文本，例如"翻译成英文：今天天气很好"

    返回:
        str: 翻译后的文本
    """
    import re
    from langgraph.config import get_config

    configurable = get_config()["configurable"]
    llm = configurable["llm"]

    # 解析目标语言和待翻译文本
    m = re.match(r"翻译(?:成|为|到)?\s*([a-zA-Z一-鿿]+)[：:]\s*(.+)", message, re.DOTALL)
    if m:
        target_lang = m.group(1).strip()
        text = m.group(2).strip()
    else:
        # 模糊匹配：去掉"翻译"前缀，其余当文本，目标语言由 LLM 推断
        text = re.sub(r"^翻译(?:成|为|到)?\s*", "", message).strip()
        target_lang = "英文"

    return await translate_text(text=text, target_lang=target_lang, llm=llm)
```

在 `create_private_butler_tools` 的 return 列表中新增 `translate`：

```python
return [
    summarize_text,
    summarize_group_chat,
    search_local_knowledge,
    search_web,
    query_weather,
    create_group_webhook_reminder,
    list_reminders,
    cancel_reminder,
    translate,
]
```

更新文件顶部 docstring 的描述，把 "八" 改为 "九"：

```python
"""Butler 工具封装
把私聊可用的摘要、知识库、联网搜索、天气、提醒和翻译能力包装为 LangChain tools
...
返回:
    list[Any]: 九个 LangChain tool，供模型工具调用使用
"""
```

- [ ] **Step 2: 提交**

```bash
git add src/agents/private_butler/tools.py
git commit -m "feat: add translate tool to PrivateButlerAgent"
```

---

### Task 3: 群聊积分 — group_policy 触发词

**Files:**
- Modify: `src/messaging/group_policy.py`

- [ ] **Step 1: 新增翻译关键词**

在现有常量区、POLL_END_KEYWORDS 之后新增：

```python
TRANSLATE_KEYWORDS = ("翻译成", "翻译为", "翻译")
```

- [ ] **Step 2: 在 classify_group_trigger 中新增翻译检查**

在 QUESTION_MARKERS 检查之前插入：

```python
if any(keyword in normalized for keyword in TRANSLATE_KEYWORDS):
    return "translate"
```

完整的 `classify_group_trigger` 中翻译检查的位置（在 poll_view 之后、QUESTION_MARKERS 之前）：

```python
if any(keyword in normalized for keyword in POLL_VIEW_KEYWORDS):
    return "poll_view"
if any(keyword in normalized for keyword in TRANSLATE_KEYWORDS):
    return "translate"
if any(marker in normalized for marker in QUESTION_MARKERS):
    return "simple_qa"
```

- [ ] **Step 3: 提交**

```bash
git add src/messaging/group_policy.py
git commit -m "feat: add translate trigger to group policy"
```

---

### Task 4: 群聊积分 — GroupMentionAgent translate_node

**Files:**
- Modify: `src/agents/group_mention/classifier.py`
- Modify: `src/agents/group_mention/nodes.py`
- Modify: `src/agents/group_mention/graph.py`

- [ ] **Step 1: classifier.py — ALLOWED_CATEGORIES 新增 "translate"**

```python
ALLOWED_CATEGORIES = {
    "summarize_group",
    "weather",
    "simple_qa",
    "unsupported",
    "poll_create",
    "poll_vote",
    "poll_view",
    "poll_end",
    "translate",
}
```

- [ ] **Step 2: nodes.py — 新增 translate_node**

在文件顶部新增 import：

```python
from src.agents.translate import translate_text
```

在文件末尾新增 `translate_node` 函数：

```python
async def translate_node(state: dict) -> dict:
    """将翻译请求翻译成目标语言

    参数:
        state: 当前图状态

    返回:
        dict: 包含翻译结果的 reply
    """
    import re

    message = state.get("message", "")
    llm = state["llm"]

    m = re.match(r"翻译(?:成|为|到)?\s*([a-zA-Z一-鿿]+)[：:]\s*(.+)", message, re.DOTALL)
    if m:
        target_lang = m.group(1).strip()
        text = m.group(2).strip()
    else:
        text = re.sub(r"^翻译(?:成|为|到)?\s*", "", message).strip()
        target_lang = "英文"

    reply = await translate_text(text=text, target_lang=target_lang, llm=llm)
    return {"reply": reply}
```

- [ ] **Step 3: nodes.py — route_by_category 新增 translate 路由**

```python
def route_by_category(state: dict) -> str:
    category = state.get("category", "unsupported")
    if category in {"summarize_group", "weather", "simple_qa"}:
        return category
    if category in {"poll_create", "poll_vote", "poll_view", "poll_end"}:
        return "poll"
    if category == "translate":
        return "translate"
    return "unsupported"
```

- [ ] **Step 4: graph.py — 注册 translate_node**

在 import 区新增 `translate_node`：

```python
from src.agents.group_mention.nodes import (
    build_initial_messages,
    call_model_with_tools,
    classify_node,
    extract_tool_reply,
    poll_node,
    route_by_category,
    simple_qa_node,
    summarize_group_node,
    translate_node,
    unsupported_node,
    weather_unavailable_node,
)
```

在 `_build_graph` 中新增节点和边：

```python
builder.add_node("translate", translate_node)
```

在 conditional_edges 中新增路由：

```python
"translate": "translate",
```

新增边到 END：

```python
builder.add_edge("translate", END)
```

- [ ] **Step 5: 提交**

```bash
git add src/agents/group_mention/classifier.py src/agents/group_mention/nodes.py src/agents/group_mention/graph.py
git commit -m "feat: add translate node and routing to GroupMentionAgent"
```

---

### Task 5: 集成验证

**Files:**
- 无新文件

- [ ] **Step 1: 验证导入和基本功能**

```bash
cd /Users/assle/dev/personal_butler_agent
uv run python -c "
from src.agents.translate import translate_text
from src.agents.private_butler.tools import create_private_butler_tools
from src.messaging.group_policy import classify_group_trigger
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 2: 验证翻译触发词**

```bash
uv run python -c "
from src.messaging.group_policy import classify_group_trigger
assert classify_group_trigger('翻译成英文：hello') == 'translate'
assert classify_group_trigger('翻译：你好') == 'translate'
assert classify_group_trigger('翻译成日文：こんにちは') == 'translate'
print('Translate trigger OK')
"
```

Expected: `Translate trigger OK`

- [ ] **Step 3: 运行现有测试**

```bash
uv run pytest tests/ -x -q
```

Expected: 全部通过

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "chore: verify translation feature integration"
```
