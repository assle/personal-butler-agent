# Troubleshooting

> Known issues and proven diagnostic steps. Load when debugging test failures, LLM errors, or WeChat callback issues.

## Tests Fail Because `DEEPSEEK_API_KEY` Is Missing

Symptom:
- Importing `src.config.settings` raises a settings validation error.

Check:
- Run tests with `DEEPSEEK_API_KEY=test uv run pytest -q`.

Reason:
- `Settings.deepseek_api_key` is required even when tests mock LLM behavior.

## Real LLM Calls Happen During Tests

Symptom:
- Tests make network calls, hang, or fail with provider errors.

Check:
- Inspect the test fixture for a mock LLM client.
- Confirm the path under test receives the mock instead of constructing a new client internally.

Fix pattern:
- Inject the LLM client through constructors or router factories.
- Keep direct `LLMClient()` construction centralized in app wiring.

## SQLite Tables Are Missing

Symptom:
- Runtime or tests fail with missing `training_records` or `user_preferences`.

Check:
- App startup should run the FastAPI lifespan in `src/main.py`.
- Tests should create metadata through `Base.metadata.create_all`.
- Ensure model modules are imported so metadata knows about all tables.

## LLM JSON Parsing Fails

Symptom:
- Intent falls back to `unknown`, or training extraction returns a parse error.

Check:
- Confirm prompts ask for JSON only.
- Confirm parsing code handles malformed JSON without raising to the API layer.

Fix pattern:
- Keep safe fallback behavior.
- Add tests with malformed JSON before tightening parsing.

## API Returns LLM Service Error

Symptom:
- Debug endpoint returns `LLM 服务暂时不可用，请稍后重试。`

Reason:
- `src/router/debug.py` catches `openai.APIError` from agent execution.

Check:
- Validate `.env` values.
- Check DeepSeek base URL, model, and key.
- Confirm network access from the runtime environment.

## Unexpected Intent

Symptom:
- A message goes to Q&A or unknown instead of the expected domain.

Check:
- Search `src/intent/rules.py` for keyword coverage.
- Check `KNOWN_INTENTS` in `src/intent/router.py`.
- Add or update tests before changing routing behavior.

## Intelligent Robot Stops Logging New Messages During LLM Reply

Symptom:
- A private chat message receives or is generating a reply.
- A group chat then @mentions the robot, but server logs do not print a new `WS: msg_callback ...` line until the earlier message finishes.
- Shutdown may also warn: `RuntimeWarning: coroutine 'WeComWSClient.stop' was never awaited`.

Reason:
- The WebSocket receive loop must keep calling `recv()`. If `_listen()` directly awaits the long-running message handler, LLM/agent work blocks receipt of subsequent WebSocket frames.
- `WeComWSClient.stop()` is async and must be awaited during FastAPI lifespan shutdown.

Check:
- Inspect `src/wechat/ws_client.py:_listen()`. Message callbacks should be scheduled with `asyncio.create_task(...)` and tracked for cleanup, not awaited inline.
- Inspect `src/main.py:lifespan()`. Shutdown should call `await app.state.ws_client.stop()`.

Fix pattern:
```python
# Receive loop stays free to read the next WebSocket frame.
task = asyncio.create_task(self._on_message(msg, req_id))
self._message_tasks.add(task)
task.add_done_callback(self._handle_message_task_done)
```

## Intelligent Robot Message Fields Are All Empty

Symptom:
- Logs show `from_user=`, `chat_type=single`, `content=` after parsing, even though the raw JSON looks correct.
- Messages are misrouted as private chat instead of group chat.

Check:
- The intelligent robot uses nested JSON fields: `from.userid`, `text.content`, `chatid`, `chattype`.
- Verify `src/wechat/message_handler.py` parses the correct nested JSON keys.

## WS 闲置时频繁断连：incorrect masking / invalid opcode

Symptom:
- 项目闲置一段时间后日志刷出 `WS disconnected: sent 1002 (protocol error) incorrect masking; no close frame received`
- 或 `WS disconnected: sent 1002 (protocol error) invalid opcode; no close frame received`
- 每次断连后 30s 自动重连成功，但闲置稍久又复现。
- 断连窗口内给智能机器人发消息，服务端没有打印 `WS: msg_callback ...`，机器人不回复。

Reason:
- TCP 连接被中间网络设备（NAT/防火墙/负载均衡器或企微服务器自身）静默断开。
- 旧实现用自定义心跳发 ping 但不校验 pong，死连接检测不及时。
- `_listen()` 仍阻塞在 `recv()` 上，当 TCP 已断开时读到残存缓冲数据/RST 包，被 websockets 库误解析为 WebSocket 帧，触发协议错误。
- 仅在 `_connect_and_listen()` 正常返回时重置 `retry_delay` 不可靠：成功订阅后通常会长期阻塞在 `_listen()`，断线时直接抛异常，因此重连退避会逐步增长到 30s。这个离线窗口内的新消息可能不会补发。

Fix (已应用):
- `src/wechat/ws_client.py` 中删除自定义 `_heartbeat()`，改用 websockets 库内置的 `ping_interval=20` + `ping_timeout=10`。
- 库内置机制在 pong 超时时同时在 ping 和 `recv()` 上抛出 `ConnectionClosed`，在读到垃圾帧之前就判定连接死亡并触发重连。
- 成功订阅后记录本次连接已建立；该连接断开时将下一次重连等待重置为 1s，避免稳定运行后的闲置断线进入 30s 离线窗口。
- 连接退出时清空 `_ws` 并标记 `_connected = False`，避免消息处理任务或定时推送使用旧连接。

Check:
- 确认 `_connect_and_listen()` 中 `ping_interval` 和 `ping_timeout` 均已设置且不为 None。
- 确认 `run()` 在 `_connected` 或 `_connection_established_for_attempt` 为真时重置 `retry_delay`。
- 如果企微服务端 pong 响应偏慢导致误断连，适当调大 `ping_timeout`（如 15-20s）。

## URL 回调模式下消息入站可靠性

Symptom:
- 用户在 WebSocket 断线窗口发消息，应用没有任何 `msg_callback` 日志，也无法补收。
- 业务目标要求“消息先被系统接住”，而不是仅缩短重连窗口。

Reason:
- WebSocket 长连接无法消除断线瞬间的离线窗口。
- URL 回调由企业微信主动投递 HTTP 请求，应用可先将回调按 `msgid` 写入 SQLite，再异步运行 LLM/agent。

Fix (已应用):
- `src/main.py` 不再启动 `WeComWSClient`。
- 新增 `GET/POST /api/wechat/aibot/callback`，使用 `WECOM_AIBOT_TOKEN` + `WECOM_AIBOT_ENCODING_AES_KEY` 做签名校验和 AES 解密。
- 新增 `inbound_messages` 表，`msgid` 唯一，重复回调不重复处理。
- 新消息先落库并返回 `{"errcode": 0, "errmsg": "ok"}`，后台处理后通过 `response_url` 回复。

Check:
- 企业微信后台 URL 配置为 `https://<域名>/api/wechat/aibot/callback`。
- `.env` 配置 `WECOM_AIBOT_BOT_ID`、`WECOM_AIBOT_TOKEN`、`WECOM_AIBOT_ENCODING_AES_KEY`。
- 数据库中 `inbound_messages.status` 应从 `pending` 变为 `processed`；失败时查看 `error` 字段。

## URL 回调报错：callback receive_id mismatch

Symptom:
- 企业微信已经 POST 到 `/api/wechat/aibot/callback`，但应用返回 `400 Bad Request`。
- 日志出现 `AIBot callback parse failed: callback receive_id mismatch`。

Reason:
- 智能机器人 URL 回调的 AES 明文尾部 receive_id 不能当作 BotID 校验。
- BotID 应从解密后的消息体字段 `aibotid` 校验；如果把 `WECOM_AIBOT_BOT_ID` 传给 AES 尾部 receive_id 校验，会在签名和解密都正确时误报 mismatch。

Fix (已应用):
- `src/wechat/callback_router.py` 构造 `WeComCallbackCrypto` 时不再传入 BotID。
- 回调帧解析完成后，使用消息体 `aibotid` 与 `WECOM_AIBOT_BOT_ID` 比较，防止其他机器人消息误入。

Check:
- 确认 `WECOM_AIBOT_BOT_ID` 填的是智能机器人后台的 BotID。
- 确认 `WECOM_AIBOT_TOKEN` 和 `WECOM_AIBOT_ENCODING_AES_KEY` 与后台 URL 回调配置一致。
