# 翻译功能设计

> 在私聊和群聊中通过 LLM 将文本翻译成任意目标语言。

## 一、核心实现

翻译逻辑集中于一个函数，不创建独立 agent：

```python
# src/agents/translate.py

async def translate_text(text: str, target_lang: str, llm) -> str:
    """调用 LLM 翻译文本到目标语言"""
    return await llm.chat([
        {"role": "system", "content": f"你是翻译助手。把用户输入翻译成{target_lang}，只返回译文，不要解释。"},
        {"role": "user", "content": text},
    ])
```

不限制语言对，LLM 能处理什么就翻什么。

## 二、私聊集成

在 `PrivateButlerAgent` 工具集中新增 `translate` tool：

- 用户："翻译成日文：今天天气很好"
- LLM 识别意图 → 调用 translate tool → 返回日文译文
- 自动被 ConversationMemory 记录

实现：在 `src/agents/private_butler/tools.py` 中新增 tool 函数，依赖 `LLMClient`。

## 三、群聊集成

### 3.1 触发识别

`group_policy.py` 新增触发词：

```python
TRANSLATE_KEYWORDS = ("翻译", "翻译成", "翻译为")
```

`classify_group_trigger` 在 QUESTION_MARKERS 之前检查 → `category="translate"`。

### 3.2 路由

`GroupMentionAgent` 新增 `translate_node`：

- `route_by_category` 新增 `"translate"` → `"translate"` 路由
- `_build_graph` 新增 `builder.add_node("translate", translate_node)` + 边

### 3.3 节点实现

```python
async def translate_node(state: dict) -> dict:
    message = state.get("message", "")
    llm = state["llm"]
    # 去掉触发词"翻译"、"翻译成"等，提取待翻译文本和目标语言
    # 如果用户说"翻译成英文：hello world"，目标语言=英文，文本=hello world
    reply = await translate_text(text=..., target_lang=..., llm=llm)
    return {"reply": reply}
```

## 四、文件布局

```
新增:
  src/agents/translate.py              # translate_text 函数

修改:
  src/agents/private_butler/tools.py   # 新增 translate tool
  src/messaging/group_policy.py        # 新增"翻译"触发词
  src/agents/group_mention/nodes.py    # 新增 translate_node
  src/agents/group_mention/graph.py    # 注册 translate_node + 路由

不需要:
  新 ORM 表、新 agent、新 scheduler
```
