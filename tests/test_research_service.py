"""
研究任务服务测试
验证任务创建幂等、工作空间隔离、每用户单任务限制、状态转换和报告查询。
"""
import pytest

from src.governance.workspaces import WorkspaceContext
from src.models.workspace import Workspace
from src.research.schemas import ResearchTaskStatus
from src.research.service import (
    InvalidResearchTransitionError,
    ResearchTaskService,
    UserResearchBusyError,
)


def _make_ws(
    workspace_id="ws-test",
    open_userid="open-u1",
    role="member",
    research_approved_once=True,
):
    """创建测试用 WorkspaceContext 辅助函数"""
    return WorkspaceContext(
        workspace_id=workspace_id,
        member_id=1,
        open_userid=open_userid,
        role=role,
        research_approved_once=research_approved_once,
    )


async def _ensure_workspace(db_session, workspace_id="ws-test"):
    """确保测试用工作空间记录存在"""
    existing = await db_session.get(Workspace, workspace_id)
    if existing is None:
        db_session.add(
            Workspace(id=workspace_id, name=f"Test {workspace_id}", status="active")
        )
        await db_session.flush()


@pytest.mark.asyncio
async def test_create_task_is_idempotent_by_source_msgid(db_session):
    """同一回调 msgid 只能创建一个任务"""
    await _ensure_workspace(db_session)
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    first, created_first = await service.create_task(
        db_session,
        workspace=_make_ws(),
        source_msgid="msg-1",
        question="比较三个知识库方案",
    )
    second, created_second = await service.create_task(
        db_session,
        workspace=_make_ws(),
        source_msgid="msg-1",
        question="这段文本应被幂等忽略",
    )
    assert created_first is True
    assert created_second is False
    assert second.id == first.id
    assert second.question == "比较三个知识库方案"


@pytest.mark.asyncio
async def test_create_task_rejects_second_active_task_for_same_user(db_session):
    """同一用户已有运行任务时拒绝创建第二个任务"""
    await _ensure_workspace(db_session)
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    await service.create_task(
        db_session,
        workspace=_make_ws(),
        source_msgid="msg-1",
        question="任务一",
    )
    with pytest.raises(UserResearchBusyError):
        await service.create_task(
            db_session,
            workspace=_make_ws(),
            source_msgid="msg-2",
            question="任务二",
        )


@pytest.mark.asyncio
async def test_create_task_allows_same_user_different_workspace(db_session):
    """同一用户在不同工作空间可以并行创建任务"""
    await _ensure_workspace(db_session, "ws-a")
    await _ensure_workspace(db_session, "ws-b")
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)

    # ws-a 创建任务
    await service.create_task(
        db_session,
        workspace=_make_ws(workspace_id="ws-a", open_userid="open-u1"),
        source_msgid="msg-1",
        question="任务一",
    )

    # ws-b 创建任务（应该成功，不同工作空间）
    task, created = await service.create_task(
        db_session,
        workspace=_make_ws(workspace_id="ws-b", open_userid="open-u1"),
        source_msgid="msg-2",
        question="任务二",
    )
    assert created is True
    assert task.workspace_id == "ws-b"


@pytest.mark.asyncio
async def test_mark_running_and_complete_persist_report(db_session):
    """任务可进入运行状态并以 unreviewed_foundation 报告完成"""
    await _ensure_workspace(db_session)
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        workspace=_make_ws(),
        source_msgid="msg-1",
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
    await _ensure_workspace(db_session)
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        workspace=_make_ws(),
        source_msgid="msg-1",
        question="研究问题",
    )
    assert await service.get_user_task(db_session, task.id, "open-u2") is None


@pytest.mark.asyncio
async def test_create_task_persists_workspace_id(db_session):
    """create_task 应持久化 workspace_id 到任务和访问范围"""
    await _ensure_workspace(db_session, "ws-specific")
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, created = await service.create_task(
        db_session,
        workspace=_make_ws(workspace_id="ws-specific"),
        source_msgid="msg-ws",
        question="workspace scoped question",
    )
    assert task.workspace_id == "ws-specific"
    assert task.access_scope["workspace_id"] == "ws-specific"


@pytest.mark.asyncio
async def test_transition_rejects_unexpected_status(db_session):
    """验证非预期状态时 transition 抛出异常"""
    await _ensure_workspace(db_session)
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        workspace=_make_ws(),
        source_msgid="msg-trans",
        question="transition test",
    )

    with pytest.raises(InvalidResearchTransitionError):
        await service.transition(
            db_session,
            task.id,
            "ws-test",
            expected={ResearchTaskStatus.RUNNING},  # task is SUBMITTED, not RUNNING
            target=ResearchTaskStatus.COMPLETED,
        )


@pytest.mark.asyncio
async def test_transition_succeeds_for_allowed_status(db_session):
    """验证合法状态转换成功"""
    await _ensure_workspace(db_session)
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        workspace=_make_ws(),
        source_msgid="msg-trans2",
        question="transition test 2",
    )

    result = await service.transition(
        db_session,
        task.id,
        "ws-test",
        expected={ResearchTaskStatus.SUBMITTED},
        target=ResearchTaskStatus.PLANNING,
    )
    assert result.status == ResearchTaskStatus.PLANNING.value
