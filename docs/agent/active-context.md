# Active Context

> Current project state, completed features, and deferred work. Load at session start or before planning feature work.

## Current State

The MVP is complete and migrated to LangChain + LangGraph. The app exposes `POST /api/debug/message`, routes replyable messages through `ButlerAgent`, a LangGraph tool-calling controller, and keeps the existing domain StateGraph agents behind tools for fitness, meal, summary, local knowledge, and web search capabilities. The intelligent robot uses URL callback mode for inbound messages, stores callbacks in SQLite by `msgid` before background processing, and replies through the callback `response_url`.

Current implementation baseline:
- FastAPI app entry: `src.main:app`
- Main reply path: `ButlerAgent` — LangGraph tool-calling loop where the LLM decides when to call training, meal, summary, local knowledge, or web search tools
- Debug route: `src/router/debug.py` — supports chat_type/chat_id for group chat simulation; replyable messages enter `ButlerAgent`
- WeChat Work intelligent robot URL callback: `src/wechat/callback_router.py` + `src/wechat/callback_inbox.py` + `src/wechat/callback_handler.py` — URL 验证、加密回调解析、按 `msgid` 幂等落库、后台处理、通过 `ButlerAgent` 和 `response_url` 回复
- Intent routing: `src/intent/rules.py` and `src/intent/router.py` remain available for compatibility and scheduler auto-routing, but are not the default reply path for debug or WeChat messages
- Agents: `ButlerAgent`, `FitnessAgent`, `SummaryAgent` (text + group), `MealAgent`, `QAAgent`
- Agent registry: `src/agents/registry.py` — 7 intent→agent mappings
- LLM: `langchain_openai.ChatOpenAI` pointed at DeepSeek
- Persistence: `training_records`, `user_preferences`, `group_messages`
- Multi-turn memory: LangGraph `MemorySaver` checkpointing (in-memory, per user_id thread)
- Verification baseline: 111 tests passing with `DEEPSEEK_API_KEY=test uv run pytest -q`
- Config: `WECOM_AIBOT_BOT_ID` + `WECOM_AIBOT_TOKEN` + `WECOM_AIBOT_ENCODING_AES_KEY` for intelligent robot URL callback mode; `SCHEDULER_TARGETS_FILE` enables APScheduler-driven Enterprise WeChat group webhook push.

## What Is Implemented

- Debug API request/response schema (with chat_type/chat_id for group simulation).
- WeChat Work intelligent robot URL 回调模式 (GET URL 验证、POST 加密回调接收、入站消息幂等落库、后台处理、通过 `response_url` 回复).
- APScheduler 企业微信群 webhook 主动推送：按本地 JSON 配置为多个群注册独立 cron，触发 ButlerAgent 生成内容后推送 markdown 到对应群 webhook。
- ButlerAgent tool-calling main entry: replyable private messages and trigger-style group messages enter a LangGraph `ToolNode` loop; the LLM decides when to call domain tools.
- Rule-first classification for known intent keywords.
- DeepSeek/OpenAI-compatible LLM fallback classification via LangChain ChatOpenAI.
- Training record extraction and persistence — supports both strength (sets/reps/weight) and cardio (duration/speed/incline/calories) training types (FitnessAgent StateGraph).
- Recent-history-based training plan generation (FitnessAgent StateGraph).
- Structured chat summarization — private chat text and group chat history (SummaryAgent StateGraph with conditional routing).
- Group chat message passive collection: all group messages saved to DB after URL callback delivery, trigger keywords ("总结"/"摘要"/"概括"/"汇总") initiate summarization.
- Preference-aware meal planning and Q&A (MealAgent, QAAgent StateGraphs).
- Agent registry for centralized intent-to-agent dispatch.
- Multi-turn conversation memory via LangGraph MemorySaver (in-memory, per user_id thread).
- Test fixtures that mock LLM behaviors and use isolated test DB setup.
- Voice message support: WeChat Work built-in voice recognition text extracted from URL callback JSON `voice.content` (intelligent robot), routed through existing intent pipeline. Empty recognition silently ignored.
- Agent personality: each agent (QA/小管家, Fitness/铁块教练, Meal/小厨, Summary/会议纪要员) has a distinct persona with defined character, speaking style, and emotional tone.
- Conversation memory: 6-turn recent messages + LLM-compressed summary persisted to SQLite; QA, Fitness(today_plan), and Meal agents maintain cross-turn context.
- Stage 1 knowledge-base RAG: SQLite-backed public/user/group scoped knowledge documents and chunks, local `.md`/`.txt` import CLI, scoped retrieval service, and QAAgent knowledge-context injection.
- Web search tool: disabled by default, configurable through `WEB_SEARCH_*`, and available to ButlerAgent as `search_web` for current/external information.
- Pure intelligent robot configuration: self-built app server API fields (`WECOM_CORP_ID`, `WECOM_CORP_SECRET`) and user-info lookup services are removed from the current runtime surface.

## Deferred Work

The README and MVP spec list these as future scope:
- RAG Stage 2/3: hybrid vector retrieval, PDF/web imports, file upload UI, index rebuild operations, and broader Fitness/Meal/Summary integration.

## Working Guidance

- Treat the current app as a working MVP with LangGraph, not a blank scaffold.
- Preserve the debug endpoint while adding real integrations unless the user asks to replace it.
- Before feature work, read `docs/agent/patterns.md` and relevant tests.
- Before changing scope or architecture, read `docs/agent/decisions.md`.
- New domain agents still follow the pattern: State → nodes → graph → register in `registry.py`; new cross-domain capabilities usually become ButlerAgent tools first.
