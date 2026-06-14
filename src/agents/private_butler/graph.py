"""
Butler Agent 图组装
构建小管家总控 LangGraph，支持 LLM 直接回复和工具调用循环

Workflow:
  START → agent(call_model) → tools_condition
  → tools → agent（有工具调用时循环）
  → extract_reply → END（无工具调用时输出最终回复）
"""
import asyncio as _asyncio
import logging as _logging
import re

from langgraph.graph import END, START, StateGraph
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import ToolNode, tools_condition

from src.agents.memory.extractor import extract_fragments as _extract_fragments, build_profile_summary as _build_profile_summary
from src.agents.private_butler.nodes import build_initial_messages, call_model, extract_reply
from src.agents.private_butler.state import PrivateButlerState
from src.agents.private_butler.tools import PrivateButlerToolContext, create_private_butler_tools
from src.graph.memory import checkpointer as _checkpointer
from src.memory.conversation import ConversationMemory
from src.schemas.response import AgentResponse

_logger = _logging.getLogger(__name__)

_RESEARCH_SUBMIT_PATTERN = re.compile(r"^(?:深度研究|研究任务)[：:]\s*(.+)$", re.DOTALL)
_RESEARCH_STATUS_PATTERN = re.compile(
    r"^查看研究任务\s+(R\d{8}-[A-F0-9]{8})$", re.IGNORECASE
)
_RESEARCH_APPROVE_PATTERN = re.compile(
    r"^批准研究任务\s+(R\d{8}-[A-F0-9]{8})$",
    re.IGNORECASE,
)
_RESEARCH_REJECT_PATTERN = re.compile(
    r"^拒绝研究任务\s+(R\d{8}-[A-F0-9]{8})(?:[：:]\s*(.+))?$",
    re.IGNORECASE | re.DOTALL,
)
_RESEARCH_HELP_PATTERN = re.compile(
    r"(?:怎么|如何|怎样|是否|能否|可以|支持|启动|开启|使用|介绍|说明|有没有|有)"
    r".{0,12}(?:深度研究|研究功能|研究任务)"
    r"|(?:深度研究|研究功能|研究任务)"
    r".{0,12}(?:怎么|如何|怎样|是否|能否|可以|支持|启动|开启|使用|介绍|说明)",
    re.IGNORECASE,
)


def _research_help_reply(research_available: bool) -> str:
    """生成研究功能使用说明；参数表示研究服务是否可用；返回帮助文本。"""
    if research_available:
        return (
            "研究功能已启用，你不需要在聊天里额外启动。\n"
            "1. 提交任务：`深度研究：<具体问题>`\n"
            "2. 查询进度：`查看研究任务 <任务ID>`\n"
            "3. 若任务需要审批：`批准研究任务 <任务ID>` 或 "
            "`拒绝研究任务 <任务ID>：<原因>`\n"
            "研究任务由后台 Taskiq Worker 异步执行，完成后会通过企业微信"
            "自建应用主动发送结果。"
        )
    return (
        "研究功能当前未启用。管理员需要配置 `RESEARCH_ENABLED=true`、Redis "
        "和企业微信自建应用参数，并同时启动 FastAPI 与 Taskiq Worker。"
    )


def _direct_reminder_intent(message: str) -> str | None:
    """识别应绕过 LLM 工具选择的提醒请求

    参数:
        message: 用户私聊原始消息

    返回:
        str | None: 提醒 intent；不是提醒请求时返回 None
    """
    text = message.strip()
    if not text:
        return None
    if re.search(r"(查看|看看|列出|有哪些).{0,8}提醒|提醒列表|我的提醒", text):
        return "list_reminders"
    if re.search(r"(取消|删除|关掉|停止).{0,8}(#?\s*\d+|提醒)", text):
        return "cancel_reminder"
    has_reminder_word = re.search(
        r"(提醒我|提醒一下|定个提醒|设置提醒|到点提醒|叫我|喊我|"
        r"制定会议|定个会议|安排会议|设个日程|添加日程|创建日程|"
        r"帮我提醒|帮我定|帮我安排|帮我设)",
        text,
    )
    has_time_word = re.search(
        r"(今天|明天|后天|今晚|早上|上午|中午|下午|晚上|每天|每周|每月|"
        r"\d{1,2}\s*[点:：]\s*\d{0,2}|周[一二三四五六日天]|"
        r"\d+\s*分钟后|\d+\s*小时后|半小时后|一会儿后)",
        text,
    )
    if has_reminder_word and has_time_word:
        return "create_group_webhook_reminder"
    return None


class PrivateButlerAgent:
    """小管家总控 agent，负责用工具调用编排私聊知识问答和提醒服务"""

    def __init__(
        self,
        llm_client,
        summary_agent,
        knowledge_service,
        web_search_service,
        weather_service=None,
        reminder_agent=None,
        memory_service=None,
        db_session_factory=None,
        research_submitter=None,
    ):
        """初始化 PrivateButlerAgent 并编译工具调用图

        参数:
            llm_client: 支持 bind_tools().ainvoke() 和 chat() 的 LLM 客户端
            summary_agent: 摘要领域 agent
            knowledge_service: 本地知识库检索服务
            web_search_service: 联网搜索服务
            weather_service: 天气服务
            reminder_agent: 提醒 agent
            memory_service: 个性化记忆服务
            db_session_factory: 异步数据库会话工厂，供旁路提取任务创建独立 session
            research_submitter: 可选研究任务提交服务

        返回:
            None
        """
        self._llm = llm_client
        self._memory_service = memory_service
        self._db_session_factory = db_session_factory
        self._research_submitter = research_submitter
        self._tool_context = PrivateButlerToolContext(
            summary_agent=summary_agent,
            knowledge_service=knowledge_service,
            web_search_service=web_search_service,
            weather_service=weather_service,
            reminder_agent=reminder_agent,
            memory_service=memory_service,
        )
        self._tools = create_private_butler_tools(self._tool_context)
        self._graph = self._build_graph()

    def _build_graph(self):
        """构建并编译 PrivateButlerAgent StateGraph

        参数:
            无

        返回:
            CompiledStateGraph: 编译后的 LangGraph 图
        """
        builder = StateGraph(PrivateButlerState)
        builder.add_node("agent", call_model)
        builder.add_node("tools", ToolNode(self._tools))
        builder.add_node("extract_reply", extract_reply)

        builder.add_edge(START, "agent")
        builder.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "tools", END: "extract_reply"},
        )
        builder.add_edge("tools", "agent")
        builder.add_edge("extract_reply", END)

        return builder.compile(checkpointer=_checkpointer)

    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理用户消息并返回小管家回复

        参数:
            intent: 意图标识，通常为 "private_butler"
            message: 用户原始消息文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话
            extra_state: 可选聊天上下文，如 chat_type/chat_id

        返回:
            AgentResponse: 小管家自然语言回复和 intent 数据
        """
        chat_type = "single"
        chat_id = None
        if extra_state:
            chat_type = extra_state.get("chat_type", chat_type)
            chat_id = extra_state.get("chat_id", chat_id)

        research_available = self._research_submitter is not None
        if chat_type == "single" and _RESEARCH_HELP_PATTERN.search(message.strip()):
            return AgentResponse(
                reply=_research_help_reply(research_available),
                data={"intent": "research_help"},
            )

        # ── 研究任务提交/查询 ──
        if chat_type == "single" and research_available:
            status_match = _RESEARCH_STATUS_PATTERN.match(message.strip())
            if status_match:
                reply = await self._research_submitter.status(
                    db,
                    task_id=status_match.group(1),
                    requester_open_userid=user_id,
                )
                return AgentResponse(reply=reply, data={"intent": "research_status"})

            submit_match = _RESEARCH_SUBMIT_PATTERN.match(message.strip())
            if submit_match:
                reply = await self._research_submitter.submit(
                    db,
                    source_msgid=(extra_state or {}).get("source_msgid", ""),
                    requester_open_userid=user_id,
                    question=submit_match.group(1).strip(),
                )
                return AgentResponse(reply=reply, data={"intent": "research_submit"})

            # ── 研究审批命令 ──
            approve_match = _RESEARCH_APPROVE_PATTERN.match(message.strip())
            if approve_match and self._research_submitter is not None:
                reply = await self._research_submitter.approve(
                    db,
                    task_id=approve_match.group(1).upper(),
                    requester_open_userid=user_id,
                )
                return AgentResponse(reply=reply, data={"intent": "research_approve"})

            reject_match = _RESEARCH_REJECT_PATTERN.match(message.strip())
            if reject_match and self._research_submitter is not None:
                reply = await self._research_submitter.reject(
                    db,
                    task_id=reject_match.group(1).upper(),
                    requester_open_userid=user_id,
                    reason=(reject_match.group(2) or "").strip(),
                )
                return AgentResponse(reply=reply, data={"intent": "research_reject"})

        direct_reminder_intent = _direct_reminder_intent(message)
        if chat_type == "single" and direct_reminder_intent:
            memory = ConversationMemory(self._llm)
            if self._tool_context.reminder_agent is None:
                reply = "提醒功能尚未初始化，请先配置 scheduler target。"
            else:
                result = await self._tool_context.reminder_agent.handle(
                    direct_reminder_intent,
                    message,
                    user_id,
                    db,
                    extra_state=extra_state,
                )
                reply = result.reply or "提醒工具没有生成有效结果。"
            await memory.save_exchange(user_id, message, reply, db)
            return AgentResponse(
                reply=reply,
                data={"intent": direct_reminder_intent},
            )

        memory = ConversationMemory(self._llm)
        summary, recent = await memory.get_context(user_id, db)

        # 检索分组画像
        profile_context = ""
        if self._memory_service is not None:
            try:
                grouped = await self._memory_service.get_profiles_grouped(db, user_id)
                if any(grouped.values()):
                    type_labels = {
                        "preference": "偏好",
                        "fact": "事实",
                        "habit": "习惯",
                        "relationship": "关系",
                    }
                    lines = []
                    for ptype, profiles in grouped.items():
                        if profiles:
                            label = type_labels.get(ptype, ptype)
                            items = [p["content"] for p in profiles]
                            lines.append(f"- {label}: {', '.join(items)}")
                    profile_context = "\n".join(lines)
            except Exception:
                pass

        if profile_context:
            _logger.info(
                "[trace:inject] user_id=%s profile_count=%d context_preview=%.200s",
                user_id, sum(1 for v in grouped.values() for _ in v),
                profile_context.replace("\n", " | "),
            )
        else:
            _logger.info("[trace:inject] user_id=%s profile_count=0 (no profiles)", user_id)

        initial_state: dict = {
            "messages": build_initial_messages(message),
            "user_id": user_id,
            "chat_type": chat_type,
            "chat_id": chat_id,
            "conversation_summary": summary,
            "recent_messages": recent,
            "profile_context": profile_context,
            "research_available": research_available,
        }
        config = {
            "configurable": {
                "db": db,
                "llm": self._llm,
                "tools": self._tools,
                "thread_id": f"private_butler:{user_id}",
                "user_id": user_id,
                "chat_type": chat_type,
                "chat_id": chat_id,
            },
            "recursion_limit": 8,
        }

        try:
            result = await self._graph.ainvoke(initial_state, config)
            reply = result.get("reply", "") or "我暂时没有生成有效回复。"
        except GraphRecursionError:
            reply = "这次工具调用太多了，我先停一下，请把需求拆小一点。"
        except Exception:
            reply = "LLM 服务暂时不可用，请稍后重试。"

        await memory.save_exchange(user_id, message, reply, db)

        # ── 旁路：异步提取画像碎片 ──
        if (
            chat_type == "single"
            and self._memory_service is not None
            and self._db_session_factory is not None
        ):
            _asyncio.create_task(
                _extract_fragments_side_path(
                    message=message,
                    user_id=user_id,
                    db_session_factory=self._db_session_factory,
                    memory_service=self._memory_service,
                    llm=self._llm,
                )
            )

        return AgentResponse(reply=reply, data={"intent": "private_butler"})


# 意图 → 记忆应用提示框架
_ACTIVE_MEMORY_TRIGGERS: list[tuple[tuple[str, ...], str]] = []


def _detect_active_memory_trigger(message: str, profile_context: str) -> str:
    """检测用户消息是否触发主动记忆应用

    参数:
        message: 用户消息
        profile_context: 已注入的画像上下文

    返回:
        str: 额外的记忆提示文本，当前暂不追加额外文本
    """
    return ""


async def _extract_fragments_side_path(
    message: str,
    user_id: str,
    db_session_factory,
    memory_service,
    llm,
) -> None:
    """旁路异步提取画像碎片：不阻塞主回复，失败不影响主功能

    参数:
        message: 用户原始消息
        user_id: 用户 ID
        db_session_factory: 返回 AsyncSession 的工厂函数
        memory_service: MemoryService 实例
        llm: LLMClient 实例
    """
    import time as _time
    t0 = _time.monotonic()

    # Stage 1: 加载已有画像
    t1 = t0
    try:
        async with db_session_factory() as db:
            grouped = await memory_service.get_profiles_grouped(db, user_id)
            profile_summary = _build_profile_summary(grouped)
        t1 = _time.monotonic()
    except Exception:
        _logger.info("[trace:sidepath] user_id=%s stage=load_profiles FAILED", user_id)
        return

    # Stage 2: LLM 提取
    fragments = await _extract_fragments(message, profile_summary, llm)
    t2 = _time.monotonic()
    if not fragments:
        _logger.info("[trace:sidepath] user_id=%s stage=extract elapsed=%.2fs result=empty",
                     user_id, t2 - t1)
        return

    _logger.info("[trace:sidepath] user_id=%s stage=extract elapsed=%.2fs result=%d_fragments",
                 user_id, t2 - t1, len(fragments))

    # Stage 3: 写入碎片 + 聚合 + 矛盾检测
    contradiction_flags: list[str] = []
    try:
        async with db_session_factory() as db:
            for f in fragments:
                await memory_service.add_fragment(
                    db=db,
                    user_id=user_id,
                    fragment_type=f["type"],
                    content=f["content"],
                    signal_strength=f["signal_strength"],
                )
                contradicted = await memory_service.detect_contradiction(
                    db, user_id, f["content"],
                )
                if contradicted is not None:
                    contradiction_flags.append(
                        f"'{f['content']}' 与已有记忆 '{contradicted.content}' 不一致"
                    )

            new_profiles = await memory_service.aggregate_fragments(db, user_id)
            await db.commit()
            t3 = _time.monotonic()

            total_elapsed = t3 - t0
            if new_profiles:
                _logger.info(
                    "[trace:sidepath] user_id=%s stage=write elapsed=%.2fs new_profiles=%d total=%.2fs profiles_detail=[%s]",
                    user_id, t3 - t2, len(new_profiles), total_elapsed,
                    ", ".join(f"{p.type}:{p.content[:30]}" for p in new_profiles),
                )
            else:
                _logger.info(
                    "[trace:sidepath] user_id=%s stage=write elapsed=%.2fs new_profiles=0 total=%.2fs",
                    user_id, t3 - t2, total_elapsed,
                )
            if contradiction_flags:
                _logger.info(
                    "[trace:sidepath] user_id=%s contradictions=%s",
                    user_id, " | ".join(contradiction_flags),
                )
    except Exception:
        _logger.info("[trace:sidepath] user_id=%s stage=write FAILED elapsed=%.2fs",
                     user_id, _time.monotonic() - t2)
