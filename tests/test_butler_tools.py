"""
Butler 工具封装测试
验证工具从 LangGraph config 读取运行时上下文，并正确调用领域 agent 与检索服务

Workflow:
  测试构造假 agent/service → create_butler_tools() 生成 LangChain tools
  → tool.ainvoke(input, config={...}) 注入 db/user/chat 上下文
  → 断言调用参数和格式化结果
"""
from unittest.mock import AsyncMock

import pytest

from src.agents.butler.tools import ButlerToolContext, create_butler_tools
from src.knowledge.schemas import KnowledgeChunkResult
from src.schemas.response import AgentResponse
from src.search.schemas import SearchResult


class FakeAgent:
    """测试用假 agent，记录 handle() 调用并返回固定回复"""

    def __init__(self, reply: str = "记录完成"):
        """初始化假 agent

        参数:
            reply: handle() 返回的回复文本

        返回:
            None
        """
        self.reply = reply
        self.handle = AsyncMock(return_value=AgentResponse(reply=reply))


def _tool_by_name(tools: list, name: str):
    """按名称取出工具

    参数:
        tools: create_butler_tools() 返回的工具列表
        name: 目标工具名称

    返回:
        BaseTool: 名称匹配的 LangChain 工具
    """
    return next(tool for tool in tools if tool.name == name)


def _runtime_config(db_session):
    """构造工具运行时配置

    参数:
        db_session: 测试数据库会话

    返回:
        dict: LangGraph/LangChain configurable 配置
    """
    return {
        "configurable": {
            "db": db_session,
            "user_id": "assle",
            "chat_type": "single",
            "chat_id": None,
        }
    }


@pytest.mark.asyncio
async def test_log_training_reads_runtime_context_and_calls_fitness_agent(db_session):
    """验证记录训练工具从 config 读取上下文并调用健身 agent

    参数:
        db_session: 测试数据库会话 fixture

    返回:
        None
    """
    fitness_agent = FakeAgent(reply="已记录卧推")
    context = ButlerToolContext(
        fitness_agent=fitness_agent,
        meal_agent=FakeAgent(),
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
    )
    tool = _tool_by_name(create_butler_tools(context), "log_training")

    result = await tool.ainvoke(
        {"message": "今天卧推 80kg 5x5"},
        config=_runtime_config(db_session),
    )

    assert result == "已记录卧推"
    fitness_agent.handle.assert_awaited_once_with(
        "log_training",
        "今天卧推 80kg 5x5",
        "assle",
        db_session,
        extra_state={"chat_type": "single", "chat_id": None},
    )


@pytest.mark.asyncio
async def test_search_web_formats_search_results(db_session):
    """验证联网搜索工具格式化 SearchResult

    参数:
        db_session: 测试数据库会话 fixture

    返回:
        None
    """
    web_search_service = AsyncMock()
    web_search_service.search.return_value = [
        SearchResult(
            title="LangChain Tools",
            url="https://example.com/tools",
            snippet="Tool calling docs",
        )
    ]
    context = ButlerToolContext(
        fitness_agent=FakeAgent(),
        meal_agent=FakeAgent(),
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=web_search_service,
    )
    tool = _tool_by_name(create_butler_tools(context), "search_web")

    result = await tool.ainvoke(
        {"query": "LangChain tool calling"},
        config=_runtime_config(db_session),
    )

    assert result == "[1] LangChain Tools\nURL: https://example.com/tools\n摘要: Tool calling docs"
    web_search_service.search.assert_awaited_once_with("LangChain tool calling")


@pytest.mark.asyncio
async def test_search_web_returns_disabled_message_when_no_results(db_session):
    """验证联网搜索无结果或未启用时返回提示

    参数:
        db_session: 测试数据库会话 fixture

    返回:
        None
    """
    web_search_service = AsyncMock()
    web_search_service.search.return_value = []
    context = ButlerToolContext(
        fitness_agent=FakeAgent(),
        meal_agent=FakeAgent(),
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=web_search_service,
    )
    tool = _tool_by_name(create_butler_tools(context), "search_web")

    result = await tool.ainvoke(
        {"query": "今天新闻"},
        config=_runtime_config(db_session),
    )

    assert result == "联网搜索没有查到结果，或当前未启用联网搜索。"


@pytest.mark.asyncio
async def test_search_local_knowledge_reads_runtime_context_and_formats_results(db_session):
    """验证本地知识库工具读取上下文并格式化检索结果

    参数:
        db_session: 测试数据库会话 fixture

    返回:
        None
    """
    knowledge_service = AsyncMock()
    knowledge_service.search.return_value = [
        KnowledgeChunkResult(
            title="训练偏好",
            source="notes.md",
            content="偏好上肢训练。",
            score=10.0,
            scope_type="user",
            domain="qa",
        )
    ]
    context = ButlerToolContext(
        fitness_agent=FakeAgent(),
        meal_agent=FakeAgent(),
        summary_agent=FakeAgent(),
        knowledge_service=knowledge_service,
        web_search_service=AsyncMock(),
    )
    tool = _tool_by_name(create_butler_tools(context), "search_local_knowledge")

    result = await tool.ainvoke(
        {"query": "训练偏好"},
        config=_runtime_config(db_session),
    )

    assert result == "[1] 训练偏好 - notes.md\n偏好上肢训练。"
    knowledge_service.search.assert_awaited_once_with(
        query="训练偏好",
        user_id="assle",
        db=db_session,
        chat_type="single",
        chat_id=None,
        domains=["global", "qa"],
        limit=5,
    )
