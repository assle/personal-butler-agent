"""
研究任务服务测试
验证任务创建幂等、每用户单任务限制、状态转换和报告查询。
"""
import pytest

from src.research.schemas import ResearchTaskStatus
from src.research.service import ResearchTaskService, UserResearchBusyError


@pytest.mark.asyncio
async def test_create_task_is_idempotent_by_source_msgid(db_session):
    """同一回调 msgid 只能创建一个任务"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    first, created_first = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="比较三个知识库方案",
    )
    second, created_second = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="这段文本应被幂等忽略",
    )
    assert created_first is True
    assert created_second is False
    assert second.id == first.id
    assert second.question == "比较三个知识库方案"


@pytest.mark.asyncio
async def test_create_task_rejects_second_active_task_for_same_user(db_session):
    """同一用户已有运行任务时拒绝创建第二个任务"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="任务一",
    )
    with pytest.raises(UserResearchBusyError):
        await service.create_task(
            db_session,
            source_msgid="msg-2",
            requester_open_userid="open-u1",
            question="任务二",
        )


@pytest.mark.asyncio
async def test_mark_running_and_complete_persist_report(db_session):
    """任务可进入运行状态并以 unreviewed_foundation 报告完成"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="研究问题",
    )
    await service.mark_running(db_session, task.id)
    report = await service.complete_with_report(
        db_session,
        task.id,
        summary="摘要",
        body="正文",
        quality_status="unreviewed_foundation",
    )
    refreshed = await service.get_task(db_session, task.id)
    assert refreshed.status == ResearchTaskStatus.COMPLETED.value
    assert refreshed.quality_status == "unreviewed_foundation"
    assert report.version == 1


@pytest.mark.asyncio
async def test_get_user_task_rejects_other_user(db_session):
    """用户不能查看其他用户的研究任务"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="研究问题",
    )
    assert await service.get_user_task(db_session, task.id, "open-u2") is None
