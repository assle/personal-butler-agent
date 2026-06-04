# Architecture Decisions

> Recorded architecture decisions and rationale. Load before making design choices or scope changes.

## ADR-001: Single-Process FastAPI MVP

The MVP is a single-process FastAPI application. It avoids Redis, Celery, Kafka, Docker, and Kubernetes until the product needs them.

Reasoning:
- The current goal is a local, understandable personal-butler demo.
- A single process keeps debugging and deployment simple.
- Future scheduling can start with APScheduler before introducing external workers.

## ADR-002: SQLite as the Memory Layer

The MVP stores training records and user preferences in SQLite through async SQLAlchemy.

Reasoning:
- SQLite is enough for local single-user or small private use.
- SQLAlchemy keeps the model layer portable if the app later moves to PostgreSQL.
- JSON preferences allow new domains to add namespaces without immediate migrations.

## ADR-003: Rule-First Intent Routing

Intent routing checks deterministic rules before calling the LLM fallback.

Reasoning:
- Common commands should be cheap, stable, and testable.
- LLM fallback handles natural-language variation without making every route probabilistic.
- Invalid LLM output must degrade to `unknown` safely.

## ADR-004: Agent-per-Domain Boundaries

Fitness, summary, meal, and Q&A behavior live in separate agent packages, each implemented as a LangGraph `StateGraph`.

Reasoning:
- Each agent can own domain prompts, DB access, validation, and response shaping.
- StateGraph nodes isolate responsibilities further: extraction, validation, persistence, and formatting are separate functions.
- Tests stay focused by domain.
- Future modules can follow the same interface (state + nodes + graph + registry) without rewriting the dispatcher.

## ADR-005: Debug Endpoint Before WeChat Work Integration

The MVP keeps `POST /api/debug/message` as the first integration surface.

Reasoning:
- It makes local and automated tests independent of WeChat Work callback signing and network setup.
- Real WeChat Work callback support should be added beside this route first, not by deleting the debug route.

## ADR-006: DeepSeek Through LangChain ChatOpenAI

The LLM wrapper uses `langchain_openai.ChatOpenAI` with configurable DeepSeek-compatible base URL and model.

Reasoning:
- It keeps provider details centralized in `src/llm/client.py`.
- Tests can mock the wrapper without touching business agents.
- Future provider changes should happen behind the wrapper.
- LangChain's ChatOpenAI provides a standard interface that integrates with LangGraph's ecosystem.

## ADR-007: LangGraph StateGraph for Agent Orchestration

Each agent is implemented as a LangGraph `StateGraph` rather than a linear class method chain.

Reasoning:
- StateGraph provides a first-class state machine that natively supports multi-step workflows, conditional routing, error recovery, and checkpointing.
- Node-per-responsibility decomposition makes agents easier to test, extend, and reason about.
- LangGraph's `MemorySaver` checkpointing gives multi-turn conversation memory with near-zero custom code.
- LangGraph is the current industry standard for agent development and aligns with interview expectations.
- Simple agents (QA, Summary) stay simple with a linear graph. Complex agents (Fitness) gain conditional routing between sub-intents.
- The `handle()` interface remains identical — callers (routes, tests, schedulers) are unaffected.

## ADR-008: 智能机器人 URL 回调作为可靠入站通道

项目使用智能机器人 URL 回调模式作为消息入站通道。WebSocket 长连接代码保留为兼容模块，但 `src/main.py` 不再启动长连接。

Reasoning:
- **避免 WS 离线窗口丢入站消息**: 长连接断线重连期间，用户消息可能不会进入应用。URL 回调由企微主动投递到公网 HTTPS 服务，入站可靠性更符合“消息不丢”的目标。
- **先落库再处理**: 回调路由按 `msgid` 写入 `inbound_messages`，重复回调幂等去重，HTTP 立即返回成功，后台再运行 LLM/agent。
- **回复不阻塞回调**: agent 处理完成后通过消息体里的 `response_url` 发送 markdown 回复，避免 LLM 调用占用 HTTP 回调响应时间。
- **可观测和可补偿**: `pending/processing/processed/failed` 状态让失败消息可查询，后续可增加启动扫描和人工重放。

Trade-off:
- URL 回调重新需要公网域名、HTTPS、Token 和 EncodingAESKey。
- `aibot_send_msg` 主动推送依赖 WebSocket；切到 URL 回调后，APScheduler 定时主动推送暂时关闭。
- 当前只保证“入站已接收可追踪”，不承诺在 response_url 过期或长时间宕机后仍能原通道回复。

## ADR-009: Sliding Window + LLM-Compressed Conversation Memory

Conversation memory uses a 6-turn (12-message) sliding window in prompt context, with older messages compressed into a single summary string by LLM and persisted to SQLite.

Reasoning:
- **Sliding window (recent messages in prompt)**: Keeps the most recent exchanges in full fidelity so agents can reference specific user statements and assistant replies. 6 turns is small enough to fit in context, large enough to cover a coherent topic thread.
- **LLM-compressed summary**: Older messages beyond the window are not discarded — they are periodically compressed into a one-sentence summary by a lightweight LLM call. This preserves key facts and preferences from earlier exchanges without consuming token budget.
- **SQLite persistence**: Summaries and messages survive process restarts, unlike LangGraph's in-memory `MemorySaver` which is only for single-session graph checkpointing.
- **Automatic compression trigger**: When a user exceeds 24 total messages, the oldest 12 are compressed. This keeps the message table bounded without manual cleanup.
- **Intent-conditional memory**: Not all agents/contexts benefit from context. `log_training` (one-shot record) and Summary agents (independent per call) skip memory loading. QA, Fitness `today_plan`, and Meal always load it.

Trade-off: The compression prompt is a separate LLM call, adding latency and cost per ~12 exchanges. For the current single-user MVP scale this is negligible. At higher throughput, compression could be deferred to a background job.

## ADR-010: Single TrainingRecord Table for Strength and Cardio

The `training_records` table was extended with nullable cardio columns (`duration_minutes`, `speed`, `incline`, `calories`) rather than creating a separate `cardio_records` table or using table inheritance.

Reasoning:
- **Unified history query**: A user's training history (`fetch_training_history`) spans both types. A single table with a `training_type` discriminator keeps the query simple — one `SELECT` with `WHERE user_id = ? ORDER BY date DESC`.
- **Shared fields**: `date`, `exercise`, `user_id`, and `created_at` are common to both types. Nullable type-specific columns avoid duplicating these.
- **MVP pragmatism**: At the current single-user scale, a separate table would add complexity (UNION queries, dual persistence paths) without meaningful benefit.
- **LLM extraction coherence**: The `EXTRACTION_PROMPT` returns a unified JSON array where each item declares its `training_type`. Persisting to one table matches this mental model.

Trade-off: Many columns will be NULL depending on training type. For a small-scale MVP this is acceptable. At higher throughput with analytics needs, a separate `cardio_records` table or a normalized schema may be more appropriate.

## ADR-011: 智能机器人 URL 回调替代长连接入站

智能机器人从 WebSocket 长连接入站切换到 URL 回调入站。

Reasoning:
- **用户目标改变**: 当前优先级从“部署简单 + 主动推送”转为“入站消息尽量不丢”。
- **WS 天然存在断线窗口**: 即便快速重连，也不能保证断线瞬间发送的消息一定送达应用。
- **URL 回调可由企微重试**: 应用收到后先持久化，降低进程内存任务失败导致消息不可追踪的风险。

Trade-off: 需要公网 HTTPS 部署；主动推送暂时不可用；如果要恢复定时推送，需要重新设计独立的主动发送通道。

## ADR-012: 移除自建应用服务端 API 依赖

智能机器人 URL 回调模式只保留 `WECOM_AIBOT_BOT_ID`、`WECOM_AIBOT_TOKEN` 和 `WECOM_AIBOT_ENCODING_AES_KEY`。项目不再暴露 `WECOM_CORP_ID` / `WECOM_CORP_SECRET`，也不再初始化基于自建应用 Secret 的用户信息查询服务。

Reasoning:
- **配置来源一致**: 智能机器人后台没有自建应用 Secret，保留该字段会误导部署。
- **集成边界更清晰**: 当前目标是可靠接收消息并通过 `response_url` 被动回复，不混入自建应用服务端 API。
- **降低启动依赖**: 应用启动不再需要额外 access_token 链路，减少配置失败面。

Trade-off: agent 上下文只使用回调消息中的 `userid`、`chatid` 等基础字段，不再查询用户姓名、部门、头像。若未来确实需要用户详情，应作为单独的自建应用/OAuth 集成重新设计。

## ADR-013: 调度器目标配置改为 JSON 文件

旧的 `.env` 扁平多字段调度配置已被 `SCHEDULER_TARGETS_FILE` JSON 目标文件取代。

Reasoning:
- 每个企业微信群需要独立 cron、webhook、触发消息和 intent，JSON 对象比多个位置配对字符串更清晰。
- webhook 地址是敏感凭据，真实 local JSON 文件可以单独加入 `.gitignore`。
- 配置文件可以保留 `enabled` 开关，便于临时关闭单个群。

Trade-off: JSON 文件比单行 `.env` 多一个本地文件，但明显降低了多群配置错位风险。

## ADR-014: ButlerAgent Tool-Calling Main Entry

Replyable user messages now enter a total-control `ButlerAgent` that binds LangChain tools to the LLM and executes them through LangGraph `ToolNode`.

Reasoning:
- The previous route-first model was stable but made every new capability depend on intent classification.
- Tool calling lets the LLM choose when to use local knowledge, web search, training, meal, and summary tools.
- Existing domain agents remain reusable behind tools, so business logic is not duplicated.
- Group non-trigger collection stays deterministic to avoid LLM work for every group message.

Trade-off:
- One user message can involve multiple LLM calls, increasing latency and cost.
- Tool descriptions and tests are now part of behavior control.
- DeepSeek tool-calling compatibility should be manually smoke-tested with a real key after unit tests pass.

## ADR-015: 企业微信群 Webhook 作为主动推送通道

URL 回调模式继续负责智能机器人入站消息和 `response_url` 被动回复；主动推送改由企业微信群机器人 webhook 独立完成。APScheduler 通过 `SCHEDULER_TARGETS_FILE` 读取本地 JSON 目标配置，为每个群注册独立 cron job，到点后调用 ButlerAgent 生成内容，再发送 markdown 到对应 webhook。

Reasoning:
- URL 回调模式不启动 WebSocket，不能继续依赖 `aibot_send_msg` 做主动推送。
- 企业微信“消息推送”类 webhook 适合群通知，不适合伪装成私聊主动推送，因此当前主动通道只面向群。
- JSON 文件比 `.env` 中多个 `|` 分隔字段更适合保存多群、多 cron、多 webhook 的配置，且真实 webhook 文件可加入 `.gitignore` 避免提交密钥。

Trade-off:
- 群 webhook 是单向推送通道，不能接收用户回复。
- webhook 地址本身是敏感凭据，需要按密钥管理。
- 每个群独立 job 会增加调度配置数量，但目标边界更清晰。
