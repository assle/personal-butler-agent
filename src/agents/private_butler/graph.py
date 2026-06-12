"""
Butler Agent 图组装
构建小管家总控 LangGraph，支持 LLM 直接回复和工具调用循环

Workflow:
  START → agent(call_model) → tools_condition
  → tools → agent（有工具调用时循环）
  → extract_reply → END（无工具调用时输出最终回复）
"""
import re

from langgraph.graph import END, START, StateGraph
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import ToolNode, tools_condition

from src.agents.private_butler.nodes import build_initial_messages, call_model, extract_reply
from src.agents.private_butler.state import PrivateButlerState
from src.agents.private_butler.tools import PrivateButlerToolContext, create_private_butler_tools
from src.graph.memory import checkpointer as _checkpointer
from src.memory.conversation import ConversationMemory
from src.schemas.response import AgentResponse


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
    has_reminder_word = re.search(r"(提醒我|提醒一下|定个提醒|设置提醒|到点提醒|叫我|喊我)", text)
    has_time_word = re.search(
        r"(今天|明天|后天|今晚|早上|上午|中午|下午|晚上|每天|每周|每月|"
        r"\d{1,2}\s*[点:：]\s*\d{0,2}|周[一二三四五六日天])",
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

        返回:
            None
        """
        self._llm = llm_client
        self._memory_service = memory_service
        self._db_session_factory = db_session_factory
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

        initial_state: dict = {
            "messages": build_initial_messages(message),
            "user_id": user_id,
            "chat_type": chat_type,
            "chat_id": chat_id,
            "conversation_summary": summary,
            "recent_messages": recent,
            "profile_context": profile_context,
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
            import asyncio
            asyncio.create_task(
                _extract_fragments_side_path(
                    message=message,
                    user_id=user_id,
                    db_session_factory=self._db_session_factory,
                    memory_service=self._memory_service,
                    llm=self._llm,
                )
            )

        return AgentResponse(reply=reply, data={"intent": "private_butler"})


import logging as _logging

from src.agents.memory.extractor import extract_fragments as _extract_fragments
from src.agents.memory.extractor import build_profile_summary as _build_profile_summary

_logger = _logging.getLogger(__name__)


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
    try:
        async with db_session_factory() as db:
            grouped = await memory_service.get_profiles_grouped(db, user_id)
            profile_summary = _build_profile_summary(grouped)
    except Exception:
        return

    fragments = await _extract_fragments(message, profile_summary, llm)
    if not fragments:
        return

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
            new_profiles = await memory_service.aggregate_fragments(db, user_id)
            await db.commit()
            if new_profiles:
                _logger.info(
                    "Memory side-path: %s new profiles for user_id=%s",
                    len(new_profiles), user_id,
                )
    except Exception:
        pass
