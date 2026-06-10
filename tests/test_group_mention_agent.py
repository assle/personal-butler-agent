"""
群聊 @ 机器人 Agent 测试
验证群聊场景只允许总结、天气和简单问答，不暴露未开放的训练/食谱能力。
"""
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_group_mention_rejects_training_request(db_session, mock_llm):
    """验证群聊里训练请求会被短拒绝"""
    from src.agents.group_mention import GroupMentionAgent

    summary_agent = AsyncMock()
    agent = GroupMentionAgent(llm_client=mock_llm, summary_agent=summary_agent)

    result = await agent.handle(
        "group_mention",
        "帮我制定今天训练计划",
        "user-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )

    assert "群聊里我只处理总结、天气和简单问答" in result.reply
    summary_agent.handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_mention_weather_unavailable(db_session, mock_llm):
    """验证未注入天气服务时返回明确的不可用回复"""
    from src.agents.group_mention import GroupMentionAgent

    agent = GroupMentionAgent(llm_client=mock_llm, summary_agent=AsyncMock())

    result = await agent.handle(
        "group_mention",
        "今天上海天气怎么样？",
        "user-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )

    assert "天气功能" in result.reply
    assert "数据源" in result.reply


@pytest.mark.asyncio
async def test_group_mention_summary_calls_summary_agent(db_session, mock_llm):
    """验证群总结请求会调用 SummaryAgent 的 summarize_group 能力"""
    from src.agents.group_mention import GroupMentionAgent

    summary_agent = AsyncMock()
    summary_agent.handle.return_value.reply = "这是群聊总结"
    summary_agent.handle.return_value.data = {"count": 3}
    agent = GroupMentionAgent(llm_client=mock_llm, summary_agent=summary_agent)

    result = await agent.handle(
        "group_mention",
        "总结一下",
        "user-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )

    assert result.reply == "这是群聊总结"
    assert result.data == {"count": 3}
    summary_agent.handle.assert_awaited_once_with(
        "summarize_group",
        "总结一下",
        "user-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )


@pytest.mark.asyncio
async def test_group_mention_simple_qa_uses_llm(db_session, mock_llm):
    """验证简单问答使用群聊轻量 prompt 直接回复"""
    from src.agents.group_mention import GroupMentionAgent

    mock_llm.chat.return_value = "可以，简单来说就是先验签再处理。"
    agent = GroupMentionAgent(llm_client=mock_llm, summary_agent=AsyncMock())

    result = await agent.handle(
        "group_mention",
        "URL 回调是什么？",
        "user-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )

    assert result.reply == "可以，简单来说就是先验签再处理。"
    mock_llm.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_group_mention_uses_preclassified_category(
    db_session,
    mock_llm,
    monkeypatch,
):
    """验证场景分发提供分类时不重复执行群聊分类

    参数:
        db_session: 测试数据库会话 fixture
        mock_llm: 测试 LLM fixture
        monkeypatch: pytest monkeypatch fixture

    返回:
        None
    """
    from src.agents.group_mention import GroupMentionAgent

    classify = AsyncMock(return_value="unsupported")
    monkeypatch.setattr(
        "src.agents.group_mention.nodes.classify_group_message",
        classify,
    )
    mock_llm.chat.return_value = "预分类后的简单回答"
    agent = GroupMentionAgent(llm_client=mock_llm, summary_agent=AsyncMock())

    result = await agent.handle(
        "group_mention",
        "这条消息不包含问号",
        "user-a",
        db_session,
        extra_state={
            "chat_type": "group",
            "chat_id": "chat-1",
            "group_category": "simple_qa",
        },
    )

    assert result.reply == "预分类后的简单回答"
    classify.assert_not_awaited()
