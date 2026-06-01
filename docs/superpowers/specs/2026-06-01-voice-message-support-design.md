# Voice Message Support Design

> 为企业微信自建应用和智能机器人回调增加语音消息支持，提取内置语音识别文本后按普通文本路由。

## Overview

- WeChat Work 自建应用和智能机器人都内置语音识别能力：自建应用 XML 中通过 `<Recognition>` 字段传递，智能机器人 JSON 中通过 `voice.content` 字段传递。
- 本项目直接使用平台已有的识别结果，不自行对接 ASR 服务。
- 语音识别文本提取后，走完全相同的意图路由和 agent 管线，不引入新意图或新 agent。
- 本次采用方案 A（内联分叉），不抽取消息类型抽象层，后续功能增多后再重构。

## Scope

### In Scope

- 自建应用回调（`src/wechat/router.py`）：解析 XML `<Recognition>`，语音识别文本当 text 路由
- 智能机器人回调（`src/wechat/robot_router.py`）：解析 JSON `voice.content`，语音识别文本当 text 路由
- 语音识别为空时静默不回复（`return Response(content="success")`），不调用 LLM

### Out of Scope

- 调试端点（`src/router/debug.py`）：暂不改
- 其他消息类型（图片、文件等）：后续再加
- 消息类型抽象层/提取器框架：后续重构时再做
- 自行对接 ASR 服务

## Design

### 1. `src/wechat/messages.py` — InnerMessage 增加 recognition 字段

自建应用 XML 的 `<Recognition>` 字段携带语音识别文本，当前 `parse_inner_xml` 未解析该字段。

**改动：**

- `InnerMessage` 新增字段：`recognition: str = ""`
- `parse_inner_xml` 新增：`recognition=_get_cdata(root, "Recognition")`

### 2. `src/wechat/robot_router.py` — 智能机器人语音处理

当前只从 `text.content` 提取文本。语音消息需要在提取步骤识别 msg_type：

```python
# 当前（约第 172 行）：
content = inner.get("text", {}).get("content", "")

# 改为：
if msg_type == "voice":
    content = inner.get("voice", {}).get("content", "")
    if not content:
        return Response(content="success")  # 识别为空，静默不回复
else:
    content = inner.get("text", {}).get("content", "")
```

同时，将第 196 行的 `msg_type != "text"` 检查改为也接受 voice：

```python
# 当前：
if msg_type != "text":

# 改为：
if msg_type not in ("text", "voice"):
```

语音识别文本提取后，群聊（存 DB + 触发词检测）和私聊（意图路由 + agent）逻辑与 text 消息完全一致。

### 3. `src/wechat/router.py` — 自建应用语音处理

当前对非 text 消息统一回复"暂不支持该消息类型"（约第 191 行）。语音需要在此检查之前拦截：

```python
# 在 "msg_type != 'text'" 检查之前插入：
if msg_type == "voice":
    content = inner.recognition
    if not content:
        return Response(content="success")
    msg_type = "text"  # 后续逻辑当 text 处理
```

语音识别文本提取后，群聊和私聊的处理逻辑与 text 消息完全一致。

## Error Handling

| 场景 | 行为 |
|------|------|
| 语音识别字段缺失（`voice.content` 或 `Recognition` 为空） | 静默返回 success，不调用 LLM |
| JSON/XML 解析失败 | 现有异常处理逻辑不变 |
| agent 处理中的 APIError | 现有 LLM 错误回复不变 |

## Testing

- 现有 82 个测试应全部通过（回归验证）
- 建议新增测试：
  - 智能机器人 voice 消息正常路由
  - 智能机器人 voice 消息识别为空 → 静默
  - 自建应用 voice 消息正常路由（XML `<Recognition>` 有值）
  - 自建应用 voice 消息识别为空 → 静默
  - `parse_inner_xml` 正确解析 `<Recognition>` 字段
