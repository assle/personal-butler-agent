"""
测试对话记忆 ORM 模型（conversation_messages + conversation_summaries）
"""
import pytest
from sqlalchemy import select, func

from src.models.conversation import ConversationMessage, ConversationSummary


async def test_save_and_retrieve_messages(db_session):
    """测试写入和读取对话消息，按时间升序排列"""
    msg1 = ConversationMessage(
        user_id="user_001", role="user", content="今天练胸",
        created_at="2026-06-02T10:00:00",
    )
    msg2 = ConversationMessage(
        user_id="user_001", role="assistant", content="好的，记录下来了！",
        created_at="2026-06-02T10:00:01",
    )
    db_session.add_all([msg1, msg2])
    await db_session.flush()

    result = await db_session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.user_id == "user_001")
        .order_by(ConversationMessage.created_at.asc())
    )
    messages = result.scalars().all()

    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "今天练胸"
    assert messages[1].role == "assistant"
    assert messages[1].content == "好的，记录下来了！"


async def test_get_recent_messages_by_user(db_session):
    """测试获取用户最近 N 条消息"""
    for i in range(20):
        db_session.add(ConversationMessage(
            user_id="user_multi",
            role="user" if i % 2 == 0 else "assistant",
            content=f"消息{i}",
            created_at=f"2026-06-02T10:{i:02d}:00",
        ))
    await db_session.flush()

    result = await db_session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.user_id == "user_multi")
        .order_by(ConversationMessage.created_at.desc())
        .limit(12)
    )
    recent = list(reversed(result.scalars().all()))

    assert len(recent) == 12
    assert recent[0].content == "消息8"
    assert recent[-1].content == "消息19"


async def test_delete_old_messages_by_user(db_session):
    """测试删除用户最早的 N 条消息"""
    for i in range(10):
        db_session.add(ConversationMessage(
            user_id="user_del",
            role="user" if i % 2 == 0 else "assistant",
            content=f"旧消息{i}",
            created_at=f"2026-06-02T10:{i:02d}:00",
        ))
    await db_session.flush()

    from sqlalchemy import delete
    subq = (
        select(ConversationMessage.id)
        .where(ConversationMessage.user_id == "user_del")
        .order_by(ConversationMessage.created_at.asc())
        .limit(6)
    )
    await db_session.execute(
        delete(ConversationMessage).where(ConversationMessage.id.in_(subq))
    )
    await db_session.flush()

    count_result = await db_session.execute(
        select(func.count()).select_from(ConversationMessage)
        .where(ConversationMessage.user_id == "user_del")
    )
    assert count_result.scalar() == 4


async def test_conversation_summary_upsert(db_session):
    """测试对话摘要的写入和更新"""
    summary = ConversationSummary(
        user_id="user_summ",
        summary_text="用户偏好练胸和背，目标是增肌",
        last_summarized_at="2026-06-02T12:00:00",
    )
    db_session.add(summary)
    await db_session.flush()

    result = await db_session.execute(
        select(ConversationSummary).where(ConversationSummary.user_id == "user_summ")
    )
    found = result.scalar_one()
    assert found.summary_text == "用户偏好练胸和背，目标是增肌"
