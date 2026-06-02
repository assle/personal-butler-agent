"""
测试 ConversationMemory 模块（get_context + save_exchange + 压缩触发）
"""
import pytest
from unittest.mock import AsyncMock

from src.memory.conversation import ConversationMemory
from src.models.conversation import ConversationMessage, ConversationSummary


async def test_get_context_empty(db_session):
    """测试空表的 get_context：返回空摘要和空消息列表"""
    mock_llm = AsyncMock()
    memory = ConversationMemory(mock_llm)
    summary, recent = await memory.get_context("user_none", db_session)

    assert summary is None
    assert recent == []


async def test_get_context_with_messages(db_session):
    """测试有消息时的 get_context：返回摘要和最近12条消息"""
    mock_llm = AsyncMock()
    from src.models.conversation import ConversationSummary

    db_session.add(ConversationSummary(
        user_id="user_with_data",
        summary_text="用户喜欢练腿",
        last_summarized_at="2026-06-02T10:00:00",
    ))
    for i in range(15):
        db_session.add(ConversationMessage(
            user_id="user_with_data",
            role="user" if i % 2 == 0 else "assistant",
            content=f"消息{i}",
            created_at=f"2026-06-02T10:{i:02d}:00",
        ))
    await db_session.flush()

    memory = ConversationMemory(mock_llm)
    summary, recent = await memory.get_context("user_with_data", db_session)

    assert summary == "用户喜欢练腿"
    assert len(recent) == 12
    assert recent[0]["role"] == "assistant"
    assert recent[0]["content"] == "消息3"


async def test_save_exchange(db_session):
    """测试 save_exchange：写入两条消息"""
    mock_llm = AsyncMock()
    memory = ConversationMemory(mock_llm)

    await memory.save_exchange("user_save", "今天练背", "好的！", db_session)

    from sqlalchemy import select
    result = await db_session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.user_id == "user_save")
        .order_by(ConversationMessage.created_at.asc())
    )
    messages = result.scalars().all()

    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "今天练背"
    assert messages[1].role == "assistant"
    assert messages[1].content == "好的！"


async def test_save_exchange_triggers_compression(db_session):
    """测试消息超过24条时触发压缩，LLM 被调用"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = "压缩后的对话摘要：用户定期训练，偏好胸背腿轮换"

    for i in range(24):
        db_session.add(ConversationMessage(
            user_id="user_compress",
            role="user" if i % 2 == 0 else "assistant",
            content=f"消息{i}",
            created_at=f"2026-06-02T10:{i:02d}:00",
        ))
    await db_session.flush()

    memory = ConversationMemory(mock_llm)
    await memory.save_exchange("user_compress", "今天练腿", "安排！", db_session)

    mock_llm.chat.assert_called_once()

    from sqlalchemy import select, func
    count_result = await db_session.execute(
        select(func.count()).select_from(ConversationMessage)
        .where(ConversationMessage.user_id == "user_compress")
    )
    assert count_result.scalar() <= 14

    summary_result = await db_session.execute(
        select(ConversationSummary).where(ConversationSummary.user_id == "user_compress")
    )
    summary = summary_result.scalar_one()
    assert "压缩后的对话摘要" in summary.summary_text
