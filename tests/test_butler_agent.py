"""
Butler Agent 图编排测试
验证小管家 StateGraph 支持直接 LLM 回复和 search_web 工具调用闭环

Workflow:
  构造 FakeToolCallingLLM 与假依赖 → PrivateButlerAgent.handle()
  → LangGraph agent 节点调用 bind_tools().ainvoke()
  → 需要工具时 ToolNode 调用 search_web 后回到 agent
  → extract_reply 返回最终 AgentResponse
"""
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolCall
from langgraph.errors import GraphRecursionError

from src.agents.private_butler import PrivateButlerAgent
from src.schemas.response import AgentResponse
from src.search.schemas import SearchResult


class FakeAgent:
    """测试用领域 agent，返回固定 AgentResponse"""

    async def handle(self, *args, **kwargs):
        """返回固定领域 agent 回复

        参数:
            *args: agent.handle() 的位置参数
            **kwargs: agent.handle() 的关键字参数

        返回:
            AgentResponse: 固定回复对象
        """
        return AgentResponse(reply="fake agent ok")


class FakeToolCallingLLM:
    """测试用工具调用 LLM，按顺序返回预设 AIMessage"""

    def __init__(self, responses: list[AIMessage]):
        """初始化假 LLM

        参数:
            responses: ainvoke() 每次调用要返回的 AIMessage 列表

        返回:
            None
        """
        self._responses = list(responses)
        self.calls: list[list] = []
        self.bound_tools = None

    def bind_tools(self, tools):
        """记录绑定工具并返回自身

        参数:
            tools: PrivateButlerAgent 传入的 LangChain tool 列表

        返回:
            FakeToolCallingLLM: 当前对象，兼容 LangChain Runnable 接口
        """
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages):
        """按顺序返回下一条 AIMessage

        参数:
            messages: 当前 LangGraph 传给模型的消息列表

        返回:
            AIMessage: 预设模型输出
        """
        self.calls.append(messages)
        return self._responses.pop(0)

    async def chat(self, *args, **kwargs):
        """兼容 ConversationMemory 压缩接口

        参数:
            *args: 未使用的位置参数
            **kwargs: 未使用的关键字参数

        返回:
            str: 固定摘要文本
        """
        return "摘要"


def _build_agent(llm, web_search_service):
    """构造 PrivateButlerAgent 测试实例

    参数:
        llm: FakeToolCallingLLM 实例
        web_search_service: 带 search() 的假联网搜索服务

    返回:
        PrivateButlerAgent: 注入假依赖的小管家 agent
    """
    return PrivateButlerAgent(
        llm_client=llm,
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=web_search_service,
    )


@pytest.mark.asyncio
async def test_butler_agent_returns_direct_llm_reply(db_session):
    """验证小管家无需工具时直接返回 LLM 回复

    参数:
        db_session: 测试数据库会话 fixture

    返回:
        None
    """
    llm = FakeToolCallingLLM([AIMessage(content="你好，我在。")])
    web_search_service = AsyncMock()
    agent = _build_agent(llm, web_search_service)

    result = await agent.handle("private_butler", "你好", "assle", db_session)

    assert result.reply == "你好，我在。"
    assert result.data == {"intent": "private_butler"}
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_butler_agent_keeps_response_intent_stable_for_compat_callers(db_session):
    """验证兼容调用传入其他 intent 时仍返回 private_butler intent

    参数:
        db_session: 测试数据库会话 fixture

    返回:
        None
    """
    llm = FakeToolCallingLLM([AIMessage(content="我来处理。")])
    web_search_service = AsyncMock()
    agent = _build_agent(llm, web_search_service)

    result = await agent.handle("qa", "你好", "assle", db_session)

    assert result.reply == "我来处理。"
    assert result.data == {"intent": "private_butler"}


@pytest.mark.asyncio
async def test_butler_agent_returns_specific_reply_on_recursion_overflow(
    db_session,
    monkeypatch,
):
    """验证工具调用超过递归限制时返回指定用户提示

    参数:
        db_session: 测试数据库会话 fixture
        monkeypatch: pytest monkeypatch fixture，用于模拟图递归溢出

    返回:
        None
    """
    llm = FakeToolCallingLLM([])
    web_search_service = AsyncMock()
    agent = _build_agent(llm, web_search_service)

    async def raise_recursion_overflow(*args, **kwargs):
        """模拟 LangGraph 递归限制异常

        参数:
            *args: ainvoke() 的位置参数
            **kwargs: ainvoke() 的关键字参数

        返回:
            None；总是抛出 GraphRecursionError
        """
        raise GraphRecursionError("recursion limit reached")

    monkeypatch.setattr(agent._graph, "ainvoke", raise_recursion_overflow)

    result = await agent.handle("private_butler", "一直搜索", "assle", db_session)

    assert result.reply == "这次工具调用太多了，我先停一下，请把需求拆小一点。"
    assert result.data == {"intent": "private_butler"}


@pytest.mark.asyncio
async def test_butler_agent_runs_search_web_tool_call_loop(db_session):
    """验证小管家能执行 search_web 工具调用并返回最终回复

    参数:
        db_session: 测试数据库会话 fixture

    返回:
        None
    """
    llm = FakeToolCallingLLM(
        [
            AIMessage(
                content="",
                tool_calls=[
                    ToolCall(
                        name="search_web",
                        args={"query": "最新韩剧"},
                        id="call-1",
                    )
                ],
            ),
            AIMessage(content="查到了：一部新韩剧正在热播。"),
        ]
    )
    web_search_service = AsyncMock()
    web_search_service.search.return_value = [
        SearchResult(
            title="新韩剧",
            url="https://example.com/kdrama",
            snippet="一部新韩剧正在热播。",
        )
    ]
    agent = _build_agent(llm, web_search_service)

    result = await agent.handle("private_butler", "搜一下最新韩剧", "assle", db_session)

    assert result.reply == "查到了：一部新韩剧正在热播。"
    web_search_service.search.assert_awaited_once_with("最新韩剧")
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_private_butler_submits_explicit_deep_research(db_session):
    """"深度研究："在私聊中创建异步任务并绕过 ReAct 图"""
    submitter = AsyncMock()
    submitter.submit.return_value = "已创建研究任务 R20260612-ABCDEF12。"
    agent = PrivateButlerAgent(
        llm_client=FakeToolCallingLLM([]),
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
        research_submitter=submitter,
    )
    result = await agent.handle(
        "private_butler",
        "深度研究：比较 Taskiq 和 Celery",
        "open-u1",
        db_session,
        extra_state={"chat_type": "single", "source_msgid": "msg-r1"},
    )
    assert result.data == {"intent": "research_submit"}
    submitter.submit.assert_awaited_once_with(
        db_session,
        source_msgid="msg-r1",
        requester_open_userid="open-u1",
        question="比较 Taskiq 和 Celery",
    )


@pytest.mark.asyncio
async def test_private_butler_explains_enabled_research_feature(db_session):
    """验证研究已启用时帮助问题直接返回用法；参数为测试会话；无返回值。"""
    submitter = AsyncMock()
    llm = FakeToolCallingLLM([])
    agent = PrivateButlerAgent(
        llm_client=llm,
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
        research_submitter=submitter,
    )

    result = await agent.handle(
        "private_butler",
        "怎么启动研究功能",
        "open-u1",
        db_session,
        extra_state={"chat_type": "single", "source_msgid": "msg-help"},
    )

    assert result.data == {"intent": "research_help"}
    assert "研究功能已启用" in result.reply
    assert "深度研究：<具体问题>" in result.reply
    assert "查看研究任务 <任务ID>" in result.reply
    assert llm.calls == []


@pytest.mark.asyncio
async def test_private_butler_explains_disabled_research_feature(db_session):
    """验证研究未启用时帮助问题说明后台配置；参数为测试会话；无返回值。"""
    llm = FakeToolCallingLLM([])
    agent = PrivateButlerAgent(
        llm_client=llm,
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
        research_submitter=None,
    )

    result = await agent.handle(
        "private_butler",
        "如何使用深度研究",
        "open-u1",
        db_session,
        extra_state={"chat_type": "single"},
    )

    assert result.data == {"intent": "research_help"}
    assert "研究功能当前未启用" in result.reply
    assert "RESEARCH_ENABLED=true" in result.reply
    assert "Taskiq Worker" in result.reply
    assert llm.calls == []


@pytest.mark.asyncio
async def test_private_butler_prompt_describes_research_availability(db_session):
    """验证通用能力问答提示词包含真实研究状态；参数为测试会话；无返回值。"""
    llm = FakeToolCallingLLM([AIMessage(content="我可以协助你。")])
    agent = PrivateButlerAgent(
        llm_client=llm,
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
        research_submitter=AsyncMock(),
    )

    await agent.handle(
        "private_butler",
        "介绍一下你的全部能力",
        "open-u1",
        db_session,
        extra_state={"chat_type": "single"},
    )

    system_prompt = llm.calls[0][0].content
    assert "异步研究功能已启用" in system_prompt
    assert "深度研究：<具体问题>" in system_prompt


@pytest.mark.asyncio
async def test_private_butler_returns_research_status(db_session):
    """"查看研究任务 ID"只允许查询当前用户任务"""
    submitter = AsyncMock()
    submitter.status.return_value = "任务已完成。"
    agent = PrivateButlerAgent(
        llm_client=FakeToolCallingLLM([]),
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
        research_submitter=submitter,
    )
    result = await agent.handle(
        "private_butler",
        "查看研究任务 R20260612-ABCDEF12",
        "open-u1",
        db_session,
        extra_state={"chat_type": "single", "source_msgid": "msg-status"},
    )
    assert result.data == {"intent": "research_status"}
