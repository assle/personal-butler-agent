"""验证企业微信智能机器人回调在 PostgreSQL 中的入站时间戳写入流程。"""

from datetime import timezone

import pytest
from sqlalchemy import select

from src.models.inbound_message import InboundMessage
from src.wechat.callback_inbox import mark_processed, record_inbound_message


@pytest.mark.asyncio
async def test_callback_inbox_accepts_utc_timestamps(postgres_session) -> None:
    """验证回调入站与处理完成时间可写入 PostgreSQL；参数为测试会话；无返回值。"""
    payload = {
        "msgid": "postgres-callback-timezone-test",
        "response_url": "https://example.com/aibot/response",
        "chattype": "single",
        "from": {"userid": "test-user"},
        "text": {"content": "你现在有什么功能"},
    }

    result = await record_inbound_message(postgres_session, payload)
    await postgres_session.commit()

    assert result.should_process is True
    assert result.message.received_at.tzinfo is not None
    assert result.message.received_at.utcoffset() == timezone.utc.utcoffset(None)

    await mark_processed(postgres_session, payload["msgid"])
    await postgres_session.commit()

    stored = await postgres_session.scalar(
        select(InboundMessage).where(InboundMessage.msgid == payload["msgid"])
    )
    assert stored is not None
    assert stored.processed_at is not None
    assert stored.processed_at.tzinfo is not None
    assert stored.processed_at.utcoffset() == timezone.utc.utcoffset(None)
