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

## URL Callback Fails With Offset-Naive And Offset-Aware Datetimes

Symptom:
- 智能机器人私聊回调写入 `inbound_messages` 时返回 `asyncpg.exceptions.DataError`。
- SQL 参数显示 UTC aware `datetime` 正在写入 `TIMESTAMP WITHOUT TIME ZONE`。

Reason:
- Python 回调流程使用 `datetime.now(timezone.utc)`。
- PostgreSQL 的旧表结构把 `received_at` 和 `processed_at` 建成了无时区时间戳。

Fix:
```bash
uv run alembic upgrade head
```

Check:
- `inbound_messages.received_at` 和 `processed_at` 应为 `timestamp with time zone`。
- 重启应用后重新发送一条智能机器人私聊消息。

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

## Research Task Is Created But Never Runs

Symptom:
- 私聊返回研究任务 ID，但任务一直停留在 submitted、planning 或等待队列状态。
- FastAPI 能正常接收 ZeroNews 等隧道转发的企业微信回调。

Reason:
- HTTPS 隧道和 PyCharm 的 FastAPI 运行配置只负责回调进程。
- 异步研究还需要独立的 Taskiq Worker 从 Redis 消费任务。

Check:
- Redis 执行 `redis-cli ping` 应返回 `PONG`。
- 进程列表中应同时存在 FastAPI 和 `taskiq worker`。

Fix:
```bash
uv run taskiq worker --ack-type when_executed \
  --workers 1 --max-async-tasks 4 \
  src.research.broker:broker src.research.tasks
```

- PyCharm 本地联调可直接选择 `local-full-stack` 运行配置。

## Research Submission Says No Workspace Access

Symptom:
- 私聊提交 `深度研究：...` 后回复“你没有访问任何工作空间的权限”。

Reason:
- `DEFAULT_WORKSPACE_ID` 和 `DEFAULT_WORKSPACE_NAME` 只描述默认空间。
- 企业微信回调用户还必须显式配置为工作空间成员。

Fix:
```env
DEFAULT_WORKSPACE_ID=default
DEFAULT_WORKSPACE_NAME=Default Workspace
DEFAULT_WORKSPACE_OWNER_OPEN_USERID=LuZhenDong
```

- `DEFAULT_WORKSPACE_OWNER_OPEN_USERID` 必须与回调日志中的 `from_user` 完全一致。
- 重启 FastAPI 后，启动引导会幂等创建默认空间和 owner 成员。

## DeepSeek Rejects Structured Response Format

Symptom:
- 研究 Worker 在规划、综合或引用审查阶段抛出
  `openai.BadRequestError: This response_format type is unavailable now`。

Reason:
- 新版 `langchain-openai` 的 `with_structured_output()` 默认使用 OpenAI
  `json_schema` response format。
- DeepSeek 的兼容接口不支持该结构化输出类型。

Fix:
- `LLMClient.ainvoke_structured()` 显式使用 `method="function_calling"`。
- 同时设置 `tool_choice="required"`，并对 HTTP 200 但结构化结果为空的情况重试一次。
- 修改后需要重启 Taskiq Worker，使 Worker 进程加载新代码。

## DeepSeek Returns HTTP 200 But Structured Result Is Empty

Symptom:
- 规划、综合或引用审查请求返回 HTTP 200。
- LangChain 的结构化结果却是 `None`，业务层随后出现 `NoneType` 属性错误。

Reason:
- DeepSeek 兼容接口可能在成功响应中既不返回正文，也不执行 schema 工具调用。
- 仅使用 `method="function_calling"` 不能保证每次都有结构化结果。

Fix:
- 结构化调用设置 `tool_choice="required"`。
- 对空结果受限重试一次；连续为空时抛出明确错误。

## Research Plan Rejects A Registered Tool

Symptom:
- Supervisor 生成的计划使用 `web.fetch`，但 `PlanValidator` 报告该工具未注册。

Reason:
- 工具已经注册到 `ResearchToolRegistry`，但 Worker 曾维护另一份手写校验白名单，
  两者发生漂移。

Fix:
- 使用 `PlanValidator.from_registry()` 从已绑定执行器的工具定义生成允许列表。
- 修改后重启 Taskiq Worker。

## Research Plan Contains Empty Synthesis Tool

Symptom:
- `PlanValidationError` 显示 `步骤 synthesize 使用了未注册的工具:`，工具名为空。

Reason:
- Supervisor 把综合、审查或投递误写成计划步骤，但这些阶段由固定研究管线自动执行，
  并不是注册工具。

Fix:
- Supervisor 提示词只允许生成证据收集工具步骤。
- 规划服务在校验前移除无工具的 synthesis/review/validation/delivery 管线步骤。

## Research Step Says It Belongs To Another Worker

Symptom:
- Worker 收到 `research.step` 后立即报告“步骤不属于当前 Worker”。
- 数据库中的步骤为 `running`，owner 形如 `dispatch:xxxxxxxx`。

Reason:
- 步骤派发器认领时生成并持久化租约 owner。
- Worker 曾忽略该 owner，改用 `worker:<step_id>` 调用执行器，导致所有权校验必然失败。
- 步骤完成后也没有重新调用步骤派发器，后续 DAG 层即使变为 `ready` 也不会入队。

Fix:
- `execute_step_job()` 必须把数据库中的 owner 原样传给步骤执行器。
- 当前步骤提交后调用 `ResearchStepDispatcher.dispatch_ready(task_id)`，继续派发新解锁步骤。
- 修改后重启 Taskiq Worker；旧的运行中租约可等待恢复任务处理，或按原 owner 安全释放。

## Research Stops After Some Sources Fail

Symptom:
- 部分研究步骤已成功并写入证据，但任务一直停在 `running`。
- 常见失败来源包括网页 404、抓取失败或可选知识库为空。

Reason:
- 管线曾只把 `completed` 和 `cancelled` 视为终结状态，任何 `failed` 步骤都会阻止综合。
- `web.fetch` 仅有 URL 时曾生成空 query，违反证据模型约束。
- PostgreSQL 知识索引曾引用 `knowledge_chunks` 表不存在的 `title` 列。

Fix:
- 有至少一个成功步骤且所有步骤均已终结时，允许部分失败任务进入综合与质量审查。
- `web.fetch` 缺少 query 时使用 URL 作为证据查询来源。
- PostgreSQL chunk 全文索引和检索表达式只使用 `content`、`source` 列。

## WeCom Proactive Delivery Fails With Error 60020

Symptom:
- 研究任务和报告已经完成，但主动私聊投递失败：
  `60020 not allow to access from your ip`。

Reason:
- Taskiq Worker 的公网出口 IP 未加入企业微信自建应用的可信 IP 列表。
- HTTPS 回调隧道只解决企业微信访问 FastAPI，不会改变 Worker 调用企业微信 API 的出口 IP。

Fix:
- 配置 `.env`：
  `WECOM_APP_CALLBACK_TOKEN`、`WECOM_APP_CALLBACK_ENCODING_AES_KEY`。
- 重启 FastAPI 后，将自建应用“接收消息服务器 URL”设置为
  `https://<ZeroNews 公网地址>/api/wechat/app/callback`，Token 和 AESKey 必须与
  `.env` 完全一致。
- URL 验证成功后，在企业微信管理后台的自建应用配置中加入 Worker 当前公网出口 IP。
- 若本地公网 IP 会变化，部署到具有固定出口 IP 的服务器后再配置可信 IP。
- 修正可信 IP 后重新派发 `research.deliver`，不需要重复执行研究任务。

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


## PostgreSQL randomblob 函数错误

Symptom: PostgreSQL 报告 function randomblob(integer) does not exist
Check: 对 PG 运行 alembic upgrade head
Cause: 迁移未按数据库方言分支
Fix: 使用 op.get_bind().dialect.name 判断，PG 路径用 substr(md5(id), 1, 16)
Regression: TEST_DATABASE_URL=... uv run pytest tests/integration -q
