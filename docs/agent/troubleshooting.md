# Troubleshooting

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

## Intelligent Robot Receives Message But No Reply in Group Chat

Symptom:
- Server logs show message decrypted, parsed, and reply generated successfully.
- `Robot reply posted: status=200, body={"errcode":40008,"errmsg":"invalid message type"}`.
- Bot does not send the reply to the group chat.

Check:
- Confirm the msgtype is `markdown`, not `text`. The intelligent robot's `response_url` only supports `markdown` and `template_card` — `text` is not supported and returns errcode 40008.
- See `src/wechat/robot_router.py:_post_reply()` for the correct payload structure.

Fix pattern:
```python
# Wrong — text not supported by robot response_url
payload = {"msgtype": "text", "text": {"content": content}}

# Correct — use markdown (or template_card)
payload = {"msgtype": "markdown", "markdown": {"content": content}}
```

## Intelligent Robot Message Fields Are All Empty

Symptom:
- Logs show `from_user=`, `chat_type=single`, `content=` after decryption, even though the raw decrypted JSON looks correct.
- Messages are misrouted as private chat instead of group chat.

Check:
- The intelligent robot uses a different JSON schema than the self-built app:
  - Robot JSON: `from.userid`, `text.content`, `chatid`, `chattype`, `response_url`
  - Self-built app: `from_user_name`, `content`, `chat_id`, `chat_type`
- The robot callback (`src/wechat/robot_router.py`) must parse the nested JSON keys, not the flat self-built app keys.

## Intelligent Robot URL Verification Fails with 403

Symptom:
- GET URL verification returns 403 with correct Token and EncodingAESKey.

Check:
- The robot uses `receiveid=""` (empty string) for echostr decryption, not CorpID.
- Verify the code calls `decrypt(encoding_aes_key, echostr, "")` — using a non-empty CorpID causes `CorpIDMismatch`.
