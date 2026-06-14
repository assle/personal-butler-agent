"""研究提交门面测试，验证审批完成后的步骤派发闭环。"""

from unittest.mock import AsyncMock

import pytest

from src.governance.workspaces import WorkspaceContext
from src.research.submission import ResearchSubmissionService


@pytest.mark.asyncio
async def test_approve_dispatches_ready_steps_after_commit(db_session) -> None:
    """验证批准后立即派发 ready 步骤；参数为测试会话；无返回值。"""
    workspace_service = AsyncMock()
    workspace_service.resolve_member.return_value = WorkspaceContext(
        workspace_id="default",
        member_id=1,
        open_userid="LuZhenDong",
        role="owner",
        research_approved_once=False,
    )
    approval_service = AsyncMock()
    step_dispatcher = AsyncMock()
    service = ResearchSubmissionService(
        AsyncMock(),
        AsyncMock(),
        workspace_service=workspace_service,
        approval_service=approval_service,
        step_dispatcher=step_dispatcher,
    )

    reply = await service.approve(
        db_session,
        task_id="R20260614-ABCDEF12",
        requester_open_userid="LuZhenDong",
    )

    assert reply.startswith("已批准研究任务")
    approval_service.approve.assert_awaited_once()
    step_dispatcher.dispatch_ready.assert_awaited_once_with(
        "R20260614-ABCDEF12"
    )
