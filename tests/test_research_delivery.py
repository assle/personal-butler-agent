"""
研究报告投递服务测试
验证企微身份映射、失败隔离和投递幂等。
"""
from unittest.mock import AsyncMock

import pytest

from src.models.research import ResearchDelivery, ResearchTask, WeComUserBinding
from src.research.delivery import ResearchDeliveryService
from src.research.service import ResearchTaskService


async def _completed_task(db_session):
    """创建带首版报告的已完成任务"""
    tasks = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await tasks.create_task(
        db_session,
        source_msgid="msg-delivery",
        requester_open_userid="open-u1",
        question="比较 Taskiq 和 Celery",
    )
    await tasks.complete_with_report(
        db_session,
        task.id,
        summary="Taskiq 更贴近 async 项目。",
        body="完整初稿",
        quality_status="unreviewed_foundation",
    )
    return tasks, task


@pytest.mark.asyncio
async def test_delivery_converts_and_persists_user_binding(db_session):
    """首次投递转换 open_userid，保存绑定并发送消息"""
    tasks, task = await _completed_task(db_session)
    client = AsyncMock()
    client.convert_open_userid.return_value = "plain-u1"
    client.send_text.return_value = "wecom-msg-1"
    service = ResearchDeliveryService(tasks, client)

    delivery = await service.deliver(db_session, task.id)

    binding = await db_session.get(WeComUserBinding, "open-u1")
    assert binding.userid == "plain-u1"
    assert delivery.status == "delivered"
    assert delivery.wecom_msgid == "wecom-msg-1"
    client.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_delivery_reuses_existing_binding(db_session):
    """已有 active 绑定时不重复调用转换接口"""
    tasks, task = await _completed_task(db_session)
    db_session.add(
        WeComUserBinding(
            open_userid="open-u1",
            userid="plain-u1",
            status="active",
        )
    )
    await db_session.flush()
    client = AsyncMock()
    client.send_text.return_value = "wecom-msg-1"

    await ResearchDeliveryService(tasks, client).deliver(db_session, task.id)

    client.convert_open_userid.assert_not_awaited()
    client.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_delivery_failure_preserves_completed_report(db_session):
    """主动推送失败只标记 delivery failed，不改变 research task completed"""
    tasks, task = await _completed_task(db_session)
    client = AsyncMock()
    client.convert_open_userid.return_value = "plain-u1"
    client.send_text.side_effect = RuntimeError("network down")

    with pytest.raises(RuntimeError, match="network down"):
        await ResearchDeliveryService(tasks, client).deliver(db_session, task.id)

    delivery = await db_session.get(ResearchDelivery, task.id)
    refreshed_task = await db_session.get(ResearchTask, task.id)
    assert delivery.status == "failed"
    assert refreshed_task.status == "completed"


@pytest.mark.asyncio
async def test_delivery_is_idempotent_after_delivered(db_session):
    """已投递任务不会重复发送"""
    tasks, task = await _completed_task(db_session)
    client = AsyncMock()
    client.convert_open_userid.return_value = "plain-u1"
    client.send_text.return_value = "wecom-msg-1"
    service = ResearchDeliveryService(tasks, client)
    await service.deliver(db_session, task.id)
    await service.deliver(db_session, task.id)
    assert client.send_text.await_count == 1
