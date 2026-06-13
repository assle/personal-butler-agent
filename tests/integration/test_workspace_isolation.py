"""
工作空间隔离集成测试
验证不同工作空间之间的研究任务数据相互隔离。
"""
import pytest

from src.governance.workspaces import WorkspaceContext
from src.models.research import ResearchTask
from src.models.workspace import Workspace, WorkspaceMember
from src.research.service import ResearchTaskService


@pytest.mark.asyncio
async def test_cross_workspace_isolation(postgres_engine, postgres_session):
    """验证 workspace-B 查询不到 workspace-A 的数据"""
    from src.db.base import Base

    # 创建所有表结构
    async with postgres_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 创建两个工作空间
    for ws_id in ("ws-a", "ws-b"):
        postgres_session.add(
            Workspace(id=ws_id, name=f"Workspace {ws_id}", status="active")
        )
    await postgres_session.flush()

    # ws-a 的成员
    postgres_session.add(
        WorkspaceMember(
            workspace_id="ws-a",
            open_userid="open-u1",
            role="member",
            status="active",
        )
    )
    await postgres_session.flush()

    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        postgres_session,
        workspace=WorkspaceContext(
            workspace_id="ws-a",
            member_id=1,
            open_userid="open-u1",
            role="member",
            research_approved_once=True,
        ),
        source_msgid="msg-iso",
        question="test isolation",
    )
    await postgres_session.flush()

    # ws-b 查询不到 ws-a 的任务
    result = await service.get_workspace_task(
        postgres_session,
        task.id,
        workspace_id="ws-b",
        requester_open_userid="open-u1",
    )
    assert result is None
