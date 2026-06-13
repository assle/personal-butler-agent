# Troubleshooting

> Known issues and proven diagnostic steps. Load when debugging test failures, LLM errors, WeChat callback issues, or scheduler webhook pushes.

## Tests Fail Because `DEEPSEEK_API_KEY` Is Missing

Symptom:
- Importing `src.config.settings` raises a settings validation error.

Check:
- Run tests with `DEEPSEEK_API_KEY=test uv run pytest -q`.

Reason:
- `Settings.deepseek_api_key` is required even when tests mock LLM behavior.

## PostgreSQL Connection Refused

Symptom:
- App startup fails with "could not connect to server" or integration tests skip with "TEST_DATABASE_URL is required".
- `brew services list` shows postgresql@16 as `none` (not running).

Check:
```bash
# 检查 PostgreSQL 是否在运行
/opt/homebrew/opt/postgresql@16/bin/pg_isready -h localhost -p 5432

# 检查 brew service 状态
brew services list | grep postgres
```

Fix:
```bash
# 启动 PostgreSQL
brew services start postgresql@16

# 如果启动失败，检查数据目录权限
ls -la /opt/homebrew/var/postgresql@16

# 验证连接
PGPASSWORD=butler /opt/homebrew/opt/postgresql@16/bin/psql \
  -h localhost -p 5432 -U butler -d butler -c "SELECT 1"
```

## PostgreSQL Role or Database Missing

Symptom:
- `FATAL: role "butler" does not exist` or `FATAL: database "butler" does not exist`.

Fix:
```bash
# 创建角色
/opt/homebrew/opt/postgresql@16/bin/psql -h localhost -p 5432 postgres -c \
  "CREATE ROLE butler WITH LOGIN PASSWORD 'butler' CREATEDB;"

# 创建数据库
for db in butler butler_test; do
  PGPASSWORD=butler /opt/homebrew/opt/postgresql@16/bin/createdb \
    -h localhost -p 5432 -U butler "$db"
done
```

## Real LLM Calls Happen During Tests

Symptom:
- Tests make network calls, hang, or fail with provider errors.

Check:
- Inspect the test fixture for a mock LLM client.
- Confirm the path under test receives the mock instead of constructing a new client internally.

Fix pattern:
- Inject the LLM client through constructors or route factories.
- Keep direct `LLMClient()` construction centralized in app wiring.

## SQLite Tables Are Missing

Symptom:
- Runtime or tests fail with missing tables such as `group_messages`, `knowledge_documents`, `reminders`, or `inbound_messages`.

Check:
- App startup should run the FastAPI lifespan in `src/main.py`.
- Tests should create metadata through `Base.metadata.create_all`.
- Ensure model modules are imported so metadata knows about all tables.

## URL Callback Mode Message Flow

Symptom:
- A user message reaches the service but does not produce the expected reply.

Check:
- Enterprise WeChat callback URL should be `https://<domain>/api/wechat/aibot/callback`.
- `.env` should set `WECOM_AIBOT_BOT_ID`, `WECOM_AIBOT_TOKEN`, and `WECOM_AIBOT_ENCODING_AES_KEY`.
- `inbound_messages.status` should move from `pending` to `processed`; failed messages should have an `error`.
- `src/messaging/inbound.py` should extract `from.userid`, `text.content` or `voice.content`, `chatid`, `chattype`, and `response_url`.

Fix pattern:
- Keep callback handling thin: parse, record, normalize, dispatch, reply.
- Do not run long LLM work before recording the inbound message.

## URL Callback Reports `callback receive_id mismatch`

Symptom:
- Enterprise WeChat POSTs to `/api/wechat/aibot/callback`, but the app returns `400 Bad Request`.
- Logs show `AIBot callback parse failed: callback receive_id mismatch`.

Reason:
- The intelligent robot callback message body `aibotid` is the BotID validation source.
- The AES plaintext tail receive_id should not be treated as the configured BotID.

Check:
- Confirm `WECOM_AIBOT_BOT_ID` matches the intelligent robot admin page.
- Confirm callback token and EncodingAESKey match the admin page.

## Group Message Does Not Reply

Symptom:
- A group callback message is saved but no reply is sent through `response_url`.

Reason:
- Group messages pass through `apply_group_policy()` before any agent runs.
- Non-trigger group messages are intentionally collected silently.
- Empty voice recognition or missing `chat_id` is ignored for reply purposes.

Check:
- Inspect `group_messages` for the saved row.
- Confirm the content includes an allowed trigger: summary keywords, weather keywords, or a simple question marker.
- Confirm unsupported training or meal requests are expected to be rejected by `GroupMentionAgent`, not handled by private tools.
- Confirm `dispatch_message()` passes `group_category` from `apply_group_policy()`; normal callback flow should not classify the same message twice.

## Scheduler Webhook Push Does Not Send

Symptom:
- APScheduler target exists but no Enterprise WeChat group message appears.

Check:
- `SCHEDULER_TARGETS_FILE` points to an existing JSON array.
- Each target has non-empty `name`, `cron`, `webhook_url`, and `message`.
- The target is not disabled with `"enabled": false`.
- For fixed text, use `"mode": "raw"` so `message` is sent directly.
- For fixed text plus weather, use `"mode": "raw"` and set `"weather_query": "今天杭州天气"` on the same target instead of creating a second weather-only target.
- `WebhookComposerAgent.handle()` is called with `intent="webhook_compose"` for `"mode": "compose"` targets; `compose` targets cannot also configure `weather_query`.
- `WebhookPushClient.send_markdown()` receives the generated markdown body.

Fix pattern:
- Treat webhook composition as scheduler-only content generation.
- Fixed content and weather should be deterministic raw composition in `SchedulerManager`; LLM composition is only for targets that explicitly need generated copy.
- The composer should generate final markdown body only for compose targets; sending belongs to `WebhookPushClient`.
- Import public scheduler APIs from `src.scheduler`; patch implementation details in tests through their owning modules such as `src.scheduler.manager.AsyncIOScheduler`.

## Private Reminder Confirmation Shows Wrong Group Name Or UTC

Symptom:
- Private chat creates a reminder successfully and the group webhook receives it, but the private confirmation shows an internal target name such as `cosmic-humor-empire` or a UTC time.

Check:
- In `SCHEDULER_TARGETS_FILE`, the target should use one group target for the actual group, for example `name="cosmic-humor-empire"` and `display_name="宇宙幽默帝国"`.
- `aliases` should contain real group names users say in private chat, such as `宇宙幽默帝国`; do not use task names such as “健身” as group aliases.
- `ReminderService.get_target_display_name()` should resolve `display_name -> aliases[0] -> name`.
- `src/agents/reminder/nodes.py` should format `next_run_at` in the reminder timezone, usually `Asia/Shanghai`.

Fix pattern:
- Keep `name` as the internal stable ID for database and job references.
- Use `display_name` only for user-facing confirmation and reminder lists.
- Treat the reminder content, such as “该健身了”, separately from the target group.

## Research Circuit Open
Symptom: web.search returns "provider degraded"
Check: Redis keys research:circuit:tavily:open
Fix: circuit auto-resets after configured open_seconds; check provider status

## Research Lease Expired
Symptom: step stuck in running with stale owner
Check: watchdog recovery log
Fix: watchdog recovers expired leases automatically every minute

## Public 404 Requests

Symptom:
- Production logs show `GET /`, `GET /health`, or `GET /v1/models` returning 404.

Reason:
- The app only exposes the WeChat callback route unless future routes are explicitly added.
- Public scanners commonly probe generic paths.
- Scheduler webhook jobs send outbound POST requests to Enterprise WeChat and do not call local app paths.

Check:
- Use `curl -i https://<domain>/api/wechat/aibot/callback` to confirm the callback route is reachable. Missing Enterprise WeChat signature parameters should fail verification rather than return 404.

Fix pattern:
- Do not treat generic public 404s as scheduler failures.
- Add a dedicated health route only if deployment monitoring requires it.

## Research Step Stuck in RETRY_WAIT

Symptom:
- Step remains in `retry_wait` status longer than expected. Worker never picks it up.

Check:
- Confirm `promote_due_retries()` is called before `claim_next()` in the dispatch path.
- `dispatch_ready()` in `ResearchStepDispatcher` calls `promote_due_retries()` before claiming.
- Watchdog `run_once()` also calls `promote_due_retries()` alongside `recover_expired_leases()`.

Fix pattern:
- Ensure every dispatch entry point promotes due retries before claiming.

## Research Step Undispatch After Recovery

Symptom:
- Watchdog recovers expired leases but steps are not re-dispatched.

Check:
- Watchdog no longer calls `enqueue_step()` directly on recovered steps.
- It calls `dispatcher.dispatch_ready()` which claims-before-enqueue.
- `dispatch_ready()` requires a database session — verify the watchdog commits the recovery before calling dispatch.

Fix pattern:
- Watchdog commits recovered/promoted steps first, then calls `dispatcher.dispatch_ready()`.

## Definition-Only Provider Registered with No Executor

Symptom:
- Tool returns "工具 {tool_name} 无可用提供者" at runtime.

Check:
- Verify `register()` was called with a `provider=` argument for the tool name.
- Some tools (e.g., `human_review`) are definition-only and cannot be executed — check the tool name against supported executor tools.

Fix pattern:
- Register executable tools with a provider instance. For definition-only tools, the registry handles the "no provider" case gracefully.

## Concurrent Research Step Claim Collision

Symptom:
- Two workers claim the same step concurrently, or a step is claimed by multiple workers.

Check:
- PostgreSQL uses `SELECT ... FOR UPDATE SKIP LOCKED` to prevent concurrent claims.
- Verify the `claim_next()` method uses `with_for_update(skip_locked=True)`.
- The integration test `test_concurrent_workers_claim_different_steps` verifies two workers get different steps.

Fix pattern:
- Ensure the database dialect supports row locking (PostgreSQL). SQLite does not support FOR UPDATE.

## Research Stage Transition Before Enqueue

Symptom:
- `queue_synthesis_if_complete()` detects all steps complete, transitions task to `SYNTHESIZING`, but the synthesis enqueue happens after commit — if the process crashes between commit and enqueue, the task is stuck.

Check:
- The pipeline commits the transition first, then calls the dispatch enqueue.
- If the dispatch enqueue fails, the transition is already committed. The task will be in `SYNTHESIZING` but not actually synthesizing.

Fix pattern:
- `queue_synthesis_if_complete()` returns False on `InvalidResearchTransitionError` — this handles the case where two concurrent calls both pass the completion check.
- The idempotency test `test_concurrent_synthesis_is_idempotent` verifies only one call succeeds.

## Research Delivery Not Idempotent Under Concurrency

Symptom:
- Two workers both attempt to deliver the same research report, sending duplicate messages.

Check:
- `deliver()` in `ResearchDeliveryService` re-reads delivery status under `FOR UPDATE` lock before sending.
- The initial check without lock is a fast path; the locked re-check ensures only one worker proceeds.

Fix pattern:
- Always re-check terminal states under row lock before writing.

## Circuit Breaker Blocks Provider Prematurely

Symptom:
- `web.search` returns "provider_circuit_open" even though the provider is healthy.

Check:
- The circuit breaker tracks consecutive failures in Redis: `research:circuit:{provider}:failures`.
- Check Redis key expiry — it is set to `open_seconds * 2` for the failure counter.
- The circuit auto-resets after `open_seconds`.

Fix pattern:
- Verify the circuit breaker configuration (`failure_threshold`, `open_seconds`) matches provider reliability expectations.

