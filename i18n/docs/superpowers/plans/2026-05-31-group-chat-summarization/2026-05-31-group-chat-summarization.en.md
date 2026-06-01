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

**Files:** `src/wechat/messages.py`, `tests/test_wechat_messages.py`

Added `chat_id` and `chat_type` fields to `InnerMessage` dataclass. Updated `parse_inner_xml()` to extract `ChatId` and `ChatType` from inner XML.

## Task 2: Create group message storage model

**Files:** `src/models/group_message.py` (new), `tests/test_group_message_model.py` (new)

Created `GroupMessage` ORM model with fields: `id`, `chat_id` (indexed), `user_id`, `content` (Text), `create_time` (int), `stored_at` (DateTime). Three class methods:
- `save()` — persist a message record
- `get_recent()` — fetch last N messages ordered by time, return in chronological order
- `cleanup()` — keep only the most recent N messages per group

## Task 3: Save group messages passively in the callback

**Files:** `src/wechat/router.py`, `tests/test_wechat_router.py`

All group chat messages (chat_type="group") are saved to DB. Non-trigger messages return empty 200 (silent collection). Trigger keyword detection: messages containing "总结", "摘要", "概括", or "汇总".

## Task 4: Implement group chat summarization node

**Files:** `src/agents/summary/state.py`, `src/agents/summary/nodes.py`, `src/agents/summary/graph.py`, `tests/test_summary.py`

Added `chat_id` and `chat_type` to `SummaryState`. Added `summarize_group_messages()` node and `GROUP_SUMMARY_PROMPT`. Added conditional routing from START based on `chat_type`: "group" → `summarize_group_messages`, else → `generate_summary`. Updated `handle()` to accept optional `extra_state` parameter. Registered `summarize_group` intent in `src/main.py`.

## Task 5: End-to-end integration and manual verification

**Debug endpoint:** Updated `DebugMessageRequest` with `chat_type` and `chat_id` fields. Updated debug router to save group messages, handle trigger detection, and route to `summarize_group`.

**E2E tests:** 4 tests in `tests/test_e2e_group_summary.py`: full flow (collect → trigger → summary), group message isolation, trigger keyword variants, empty group handling.

**Manual steps:**
1. WeChat Work admin → enable "Group Chat Messages"
2. Add bot to test group chat
3. Deploy and send normal messages to build history
4. @bot with "总结一下群消息" → verify structured summary reply

---

## Key Design Decisions

1. **Passive collection + trigger-based reply:** All group messages saved silently. Only @mention + summarize keyword triggers reply.
2. **Per-group message cap at 200:** Prevents unbounded DB growth.
3. **Reuse existing SummaryAgent:** `summarize_group` branch added via conditional routing.
4. **@mention detection via keyword matching:** Trigger keywords in content sufficient for detection.

---

## Follow-up: Intelligent Robot Callback Integration (completed 2026-05-31)

After deploying the self-built app callback, real-world testing revealed that the **intelligent robot (智能机器人) API mode** uses a fundamentally different protocol from the self-built app.

### Robot callback fixes

- [x] **Fix 1: Add robot-specific config** — `WECHAT_ROBOT_TOKEN` + `WECHAT_ROBOT_ENCODING_AES_KEY` in `src/config.py` and `.env.example`

- [x] **Fix 2: Create robot callback router** — `src/wechat/robot_router.py` with `GET/POST /api/wechat/robot/callback`

- [x] **Fix 3: Parse intelligent robot JSON format** — The robot sends a different JSON schema: `from.userid` (nested), `text.content` (nested), `chatid`, `chattype`, `response_url` — completely different from the self-built app's flat `from_user_name`/`content`/`chat_id` fields.

- [x] **Fix 4: Active reply via response_url** — The robot does not support passive encrypted XML reply. Instead, `_post_reply()` POSTs JSON to the `response_url` from the callback message. This also avoids the 5-second timeout limitation of passive reply.

- [x] **Fix 5: Use markdown msgtype** — The robot's `response_url` only supports `markdown` and `template_card` msgtypes. Using `text` returns errcode 40008 ("invalid message type"). Changed `_post_reply()` payload from `text` to `markdown`.

- [x] **Fix 6: Empty receiveid in crypto** — The robot's URL verification and message decryption use `receiveid=""` (empty string), not CorpID. GET echostr decrypt calls `decrypt(key, echostr, "")`.

### Robot-specific architecture decisions

| Aspect | Self-Built App | Intelligent Robot |
|--------|---------------|-------------------|
| Route | `/api/wechat/callback` | `/api/wechat/robot/callback` |
| Config | `WECHAT_CORP_ID` + `WECHAT_TOKEN` + `WECHAT_ENCODING_AES_KEY` | `WECHAT_ROBOT_TOKEN` + `WECHAT_ROBOT_ENCODING_AES_KEY` |
| Message format | XML or flat JSON (`FromUserName`, `Content`, `ChatId`) | Nested JSON (`from.userid`, `text.content`, `chatid`, `response_url`) |
| Reply mechanism | Passive encrypted XML in HTTP response | Active POST JSON to `response_url` |
| Reply msgtypes | `text` (via XML) | `markdown`, `template_card` only |
| Crypto receiveid | CorpID | `""` (empty string) |
| 5-second timeout | Yes (passive reply) | No (active reply) |
| Documented in | `src/wechat/router.py` | `src/wechat/router.py` + ADR-008 |

### Verification

- 14 tests in `tests/test_wechat_robot_router.py` covering: GET URL verification (receiveid=""), POST robot JSON parsing, group trigger summarization via response_url, non-trigger silent collection, CorpID isolation from self-built app.
- 82 total tests passing.
- Production verified: @bot + "总结" successfully returns markdown-formatted summary in group chat.
