# Voice Message Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add voice message support to WeChat Work self-built app and intelligent robot callbacks by extracting built-in voice recognition text and routing it through the existing intent pipeline.

**Architecture:** Three targeted edits — (1) `InnerMessage` gains a `recognition` field parsed from XML `<Recognition>`, (2) self-built app router intercepts `msg_type="voice"` before the non-text rejection, (3) intelligent robot router extracts `voice.content` from JSON and updates the non-text gate. No new abstractions, no new intents, no new agents.

**Tech Stack:** Python 3.13+, FastAPI, pytest, pytest-asyncio

---

### Task 1: Add voice recognition field to InnerMessage

**Files:**
- Modify: `src/wechat/messages.py:26-35`
- Test: `tests/test_wechat_messages.py` (add test)

- [ ] **Step 1: Write the failing test for recognition parsing**

Add this test to `tests/test_wechat_messages.py`:

```python
VOICE_INNER_XML = """<xml>
<ToUserName><![CDATA[wx123456]]></ToUserName>
<FromUserName><![CDATA[user_voice_001]]></FromUserName>
<CreateTime>1234567890</CreateTime>
<MsgType><![CDATA[voice]]></MsgType>
<Recognition><![CDATA[今天练胸肌]]></Recognition>
<MsgId>100003</MsgId>
</xml>"""


def test_parse_inner_xml_voice_recognition():
    """测试解析语音消息 XML：正确提取 Recognition 字段

    输入: 包含 <Recognition> 的 voice 消息 XML
    输出: InnerMessage(recognition="今天练胸肌", msg_type="voice", content="")
    """
    result = parse_inner_xml(VOICE_INNER_XML)

    assert result.msg_type == "voice"
    assert result.recognition == "今天练胸肌"
    assert result.content == ""
```

```python
VOICE_INNER_XML_NO_RECOGNITION = """<xml>
<ToUserName><![CDATA[wx123456]]></ToUserName>
<FromUserName><![CDATA[user_voice_002]]></FromUserName>
<CreateTime>1234567890</CreateTime>
<MsgType><![CDATA[voice]]></MsgType>
<MsgId>100004</MsgId>
</xml>"""


def test_parse_inner_xml_voice_no_recognition():
    """测试解析没有 Recognition 字段的语音消息 XML：recognition 为空字符串

    输入: 无 <Recognition> 标签的 voice 消息 XML
    输出: InnerMessage(recognition="")
    """
    result = parse_inner_xml(VOICE_INNER_XML_NO_RECOGNITION)

    assert result.msg_type == "voice"
    assert result.recognition == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wechat_messages.py::test_parse_inner_xml_voice_recognition tests/test_wechat_messages.py::test_parse_inner_xml_voice_no_recognition -v`

Expected: both FAIL — `InnerMessage.__init__()` got an unexpected keyword argument 'recognition', or `AttributeError: 'InnerMessage' object has no attribute 'recognition'`

- [ ] **Step 3: Add recognition field to InnerMessage and parse it**

In `src/wechat/messages.py`:

Change the `InnerMessage` dataclass — add `recognition` field:
```python
@dataclass
class InnerMessage:
    """解密后的内层明文消息"""
    to_user_name: str    # 企业 CorpID
    from_user_name: str  # 发送者 OpenID，用作 user_id
    create_time: int     # 消息创建时间戳
    msg_type: str        # 消息类型（text/image/voice 等）
    content: str         # 消息内容（文本消息时）
    msg_id: str          # 消息 ID
    chat_id: str = ""    # 群聊 ID，私聊时为空
    chat_type: str = "single"  # 会话类型："single"（私聊）或 "group"（群聊）
    recognition: str = ""  # 语音识别文本（voice 消息时），非 voice 消息为空
```

In `parse_inner_xml` — add `Recognition` parsing:
```python
def parse_inner_xml(decrypted: str) -> InnerMessage:
    root = ElementTree.fromstring(decrypted)
    return InnerMessage(
        to_user_name=_get_cdata(root, "ToUserName"),
        from_user_name=_get_cdata(root, "FromUserName"),
        create_time=int(_get_cdata(root, "CreateTime") or "0"),
        msg_type=_get_cdata(root, "MsgType"),
        content=_get_cdata(root, "Content"),
        msg_id=_get_cdata(root, "MsgId"),
        chat_id=_get_cdata(root, "ChatId"),
        chat_type=_get_cdata(root, "ChatType") or "single",
        recognition=_get_cdata(root, "Recognition"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_wechat_messages.py -v`

Expected: all 7 tests PASS (5 existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add src/wechat/messages.py tests/test_wechat_messages.py
git commit -m "feat: add voice recognition field to InnerMessage"
```

---

### Task 2: Voice handling in self-built app router

**Files:**
- Modify: `src/wechat/router.py:189-194`
- Test: `tests/test_wechat_router.py` (add 2 tests)

- [ ] **Step 1: Write failing tests for self-built app voice routing**

Add to `tests/test_wechat_router.py`:

```python
async def test_post_callback_voice_message_with_recognition(
    wechat_config, intent_router, agent_registry, db_session
):
    """测试自建应用 POST 语音消息（有 Recognition）：识别文本应当作普通文本路由

    输入: msg_type="voice" + recognition="今天练上肢" 的加密消息（JSON 格式，模拟内层）
    输出: 200 + XML 加密回复；agent 流水线被调用且收到识别文本
    """
    token = wechat_config["token"]
    aes_key = wechat_config["encoding_aes_key"]
    corp_id = wechat_config["corp_id"]

    inner = {
        "from_user_name": "user_voice_001",
        "msg_type": "voice",
        "content": "",
        "recognition": "今天练上肢",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), corp_id)

    timestamp = str(int(time.time()))
    nonce = "test_nonce_voice"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_app(wechat_config, intent_router, agent_registry, db_session)

    response = client.post(
        "/api/wechat/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={
            "to_user_name": corp_id,
            "agent_id": "1000001",
            "encrypt": encrypted_content,
        },
    )

    assert response.status_code == 200
    # agent 流水线应被调用（语音识别文本作为 text 路由）
    intent_router.route.assert_called()
    # 验证路由传入的是识别文本，不是空字符串
    call_arg = intent_router.route.call_args[0][0]
    assert call_arg == "今天练上肢"


async def test_post_callback_voice_message_empty_recognition(
    wechat_config, intent_router, agent_registry, db_session
):
    """测试自建应用 POST 语音消息（无 Recognition）：应静默返回不调用 agent

    输入: msg_type="voice" + recognition="" 的加密消息
    输出: 200 + body "success"；agent 未被调用
    """
    token = wechat_config["token"]
    aes_key = wechat_config["encoding_aes_key"]
    corp_id = wechat_config["corp_id"]

    inner = {
        "from_user_name": "user_voice_002",
        "msg_type": "voice",
        "content": "",
        "recognition": "",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), corp_id)

    timestamp = str(int(time.time()))
    nonce = "test_nonce_voice_empty"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_app(wechat_config, intent_router, agent_registry, db_session)

    response = client.post(
        "/api/wechat/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={
            "to_user_name": corp_id,
            "agent_id": "1000001",
            "encrypt": encrypted_content,
        },
    )

    assert response.status_code == 200
    assert response.text.strip() == "success"
    # agent 不应被调用（空识别文本，静默忽略）
    intent_router.route.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_wechat_router.py::test_post_callback_voice_message_with_recognition tests/test_wechat_router.py::test_post_callback_voice_message_empty_recognition -v`

Expected: FAIL — the voice message with recognition falls through to "暂不支持该消息类型" instead of routing; the empty recognition test may pass if voice messages are treated as non-text (assert_not_called passes), but we want explicit voice handling, so the first test definitely fails.

- [ ] **Step 3: Add voice intercept in router.py**

In `src/wechat/router.py`, insert voice handling **after the XML/JSON parse block** (after line 170, which ends the JSON fallback `except`) and **before** the group message save block (line 177). This placement ensures voice recognition text is saved as group message content when applicable.

The inner message parse block produces two possible types for `inner`:
- XML path: `InnerMessage` dataclass — access recognition via `inner.recognition`
- JSON fallback path: `dict` — access via `inner.get("recognition", "")`

So we branch on type:

```python
        # 语音消息：从 Recognition 字段提取识别文本，空则静默忽略
        if msg_type == "voice":
            voice_text = (
                inner.recognition
                if not isinstance(inner, dict)
                else inner.get("recognition", "")
            )
            if not voice_text:
                logger.info("WeChat callback: voice recognition empty, silently ignoring")
                return Response(content="success")
            content = voice_text
            msg_type = "text"
            logger.info("WeChat callback: voice recognition: %s", content[:200])

        # 非文本消息：回复不支持
        intent = "non_text"
        if msg_type != "text":
            ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_wechat_router.py -v`

Expected: all 11 tests PASS (9 existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add src/wechat/router.py tests/test_wechat_router.py
git commit -m "feat: add voice message handling to self-built app callback"
```

---

### Task 3: Voice handling in intelligent robot router

**Files:**
- Modify: `src/wechat/robot_router.py:170-173, 196`
- Test: `tests/test_wechat_robot_router.py` (add 2 tests, update 1 existing)

- [ ] **Step 1: Write new tests and update existing non-text test**

Add to `tests/test_wechat_robot_router.py`:

```python
async def test_robot_post_callback_voice_message(
    robot_config, robot_intent_router, robot_agent_registry, db_session, mock_httpx_post
):
    """测试智能机器人 POST 语音消息：识别文本走正常意图路由

    输入: msgtype="voice" + voice.content="今天练胸" 的智能机器人 JSON 格式加密消息
    输出: 200 "success"；agent 流水线被调用；回复 POST 到 response_url
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    inner = {
        "msgid": "test_msg_voice_001",
        "aibotid": "aibTestBot123",
        "chattype": "single",
        "from": {"userid": "robot_voice_user_001"},
        "msgtype": "voice",
        "voice": {"content": "今天练胸"},
        "response_url": "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=test_resp_voice",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce_voice"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, robot_intent_router, robot_agent_registry, db_session)

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={"encrypt": encrypted_content},
    )

    assert response.status_code == 200
    assert response.text.strip() == "success"

    # agent 流水线应被调用（语音识别文本走正常路由）
    robot_intent_router.route.assert_called()
    robot_agent_registry.get.assert_called()
    robot_agent_registry.get().handle.assert_called()

    # 回复通过 response_url 推送
    mock_httpx_post.assert_called_once()
    sent_payload = mock_httpx_post.call_args[1]["json"]
    assert sent_payload["markdown"]["content"] == "这是机器人测试回复"


async def test_robot_post_callback_voice_message_empty(
    robot_config, robot_intent_router, robot_agent_registry, db_session, mock_httpx_post
):
    """测试智能机器人 POST 语音消息（识别为空）：静默不回复

    输入: msgtype="voice" + voice.content="" 的智能机器人 JSON 格式加密消息
    输出: 200 "success"；agent 未被调用；response_url 未被调用
    """
    token = robot_config["token"]
    aes_key = robot_config["encoding_aes_key"]

    inner = {
        "msgid": "test_msg_voice_002",
        "aibotid": "aibTestBot123",
        "chattype": "single",
        "from": {"userid": "robot_voice_user_002"},
        "msgtype": "voice",
        "voice": {"content": ""},
        "response_url": "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=test_resp_voice_empty",
    }
    encrypted_content = encrypt(aes_key, json.dumps(inner, ensure_ascii=False), "")

    timestamp = str(int(time.time()))
    nonce = "robot_test_nonce_voice_empty"
    msg_signature = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypted_content])).encode()
    ).hexdigest()

    client = _build_robot_app(robot_config, robot_intent_router, robot_agent_registry, db_session)

    response = client.post(
        "/api/wechat/robot/callback",
        params={
            "msg_signature": msg_signature,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        json={"encrypt": encrypted_content},
    )

    assert response.status_code == 200
    assert response.text.strip() == "success"

    # agent 不应被调用
    robot_intent_router.route.assert_not_called()
    # response_url 不应被调用
    mock_httpx_post.assert_not_called()
```

Also update the existing `test_robot_post_callback_non_text_message` — the test name and comment should clarify it tests non-text-non-voice types. No code changes needed since image messages still get "暂不支持".

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_wechat_robot_router.py::test_robot_post_callback_voice_message tests/test_wechat_robot_router.py::test_robot_post_callback_voice_message_empty -v`

Expected: FAIL — voice messages currently hit the `msg_type != "text"` gate and get "暂不支持该消息类型", so the first test's `assert_called` assertions fail.

- [ ] **Step 3: Add voice handling in robot_router.py**

Two changes in `src/wechat/robot_router.py`:

**Change A — Extract voice content (replace line 172):**

```python
        # 根据消息类型提取文本内容
        if msg_type == "voice":
            content = inner.get("voice", {}).get("content", "")
            if not content:
                logger.info("Robot callback: voice recognition empty, silently ignoring")
                return Response(content="success")
            logger.info("Robot callback: voice recognition: %s", content[:200])
        else:
            content = inner.get("text", {}).get("content", "")
```

**Change B — Update non-text gate (line 196):**

```python
        # 非文本且非语音消息
        if msg_type not in ("text", "voice"):
            reply_text = "暂不支持该消息类型"
```

The `msg_type != "text"` condition changes to `msg_type not in ("text", "voice")`.

- [ ] **Step 4: Run all robot router tests**

Run: `uv run pytest tests/test_wechat_robot_router.py -v`

Expected: all 12 tests PASS (10 existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add src/wechat/robot_router.py tests/test_wechat_robot_router.py
git commit -m "feat: add voice message handling to intelligent robot callback"
```

---

### Task 4: Full regression verification

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`

Expected: all tests PASS (82 original + 6 new = 88)

- [ ] **Step 2: Verify no other test files changed**

Run: `uv run pytest tests/test_wechat_messages.py tests/test_wechat_router.py tests/test_wechat_robot_router.py -v`

Expected: all 3 files, all tests PASS

---

### Task 5: Final commit for documentation sync

- [ ] **Step 1: Update active-context.md with voice support**

In `docs/agent/active-context.md`, add to "What Is Implemented" section:
```
- Voice message support: WeChat Work built-in voice recognition text extracted from XML `<Recognition>` (self-built app) and JSON `voice.content` (intelligent robot), routed through existing intent pipeline. Empty recognition silently ignored.
```

- [ ] **Step 2: Commit**

```bash
git add docs/agent/active-context.md
git commit -m "docs: add voice message support to active context"
```
