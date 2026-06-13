"""
工作空间解析服务测试
验证 WorkspaceService 能正确解析工作空间成员身份并处理异常情况
"""
import pytest
from sqlalchemy import select

from src.models.workspace import Workspace, WorkspaceMember


async def seed_workspace_member(db, workspace_id, open_userid, role="member"):
    """在测试数据库中创建 Workspace 和 WorkspaceMember 记录

    参数:
        db: 异步数据库会话
        workspace_id: 工作空间 ID
        open_userid: 企业微信用户 open_userid
        role: 成员角色，默认 "member"

    返回:
        tuple: (Workspace, WorkspaceMember) 创建的工作空间和成员对象
    """
    ws = Workspace(
        id=workspace_id,
        name=f"测试工作空间 {workspace_id}",
        status="active",
    )
    db.add(ws)
    await db.flush()
    member = WorkspaceMember(
        workspace_id=workspace_id,
        open_userid=open_userid,
        role=role,
        status="active",
    )
    db.add(member)
    await db.flush()
    return ws, member


@pytest.mark.asyncio
async def test_resolve_active_membership_returns_workspace_context(db_session):
    """验证活动成员可解析工作空间上下文"""
    workspace, member = await seed_workspace_member(
        db_session,
        workspace_id="ws-a",
        open_userid="open-u1",
        role="member",
    )
    from src.governance.workspaces import WorkspaceService
    service = WorkspaceService()
    context = await service.resolve_member(db_session, "open-u1")
    assert context.workspace_id == workspace.id
    assert context.member_id == member.id
    assert context.role == "member"


@pytest.mark.asyncio
async def test_resolve_member_rejects_ambiguous_membership(db_session):
    """验证多工作空间身份必须显式选择，不能静默越权"""
    await seed_workspace_member(db_session, "ws-a", "open-u1", "member")
    await seed_workspace_member(db_session, "ws-b", "open-u1", "member")
    from src.governance.workspaces import WorkspaceService, AmbiguousWorkspaceError
    with pytest.raises(AmbiguousWorkspaceError):
        await WorkspaceService().resolve_member(db_session, "open-u1")


@pytest.mark.asyncio
async def test_resolve_member_rejects_no_membership(db_session):
    """验证不属于任何工作空间的用户被拒绝访问"""
    from src.governance.workspaces import WorkspaceService, WorkspaceAccessDeniedError
    with pytest.raises(WorkspaceAccessDeniedError):
        await WorkspaceService().resolve_member(db_session, "unknown-user")


@pytest.mark.asyncio
async def test_resolve_member_with_explicit_workspace_id(db_session):
    """验证显式指定工作空间 ID 时直接定位到对应成员"""
    await seed_workspace_member(db_session, "ws-a", "open-u1", "member")
    await seed_workspace_member(db_session, "ws-b", "open-u1", "member")
    from src.governance.workspaces import WorkspaceService
    context = await WorkspaceService().resolve_member(db_session, "open-u1", workspace_id="ws-a")
    assert context.workspace_id == "ws-a"
    assert context.role == "member"


@pytest.mark.asyncio
async def test_resolve_member_respects_inactive_workspace(db_session):
    """验证非活动工作空间的成员不被识别"""
    ws = Workspace(id="ws-inactive", name="停用工作空间", status="inactive")
    db_session.add(ws)
    await db_session.flush()
    member = WorkspaceMember(
        workspace_id="ws-inactive",
        open_userid="open-u1",
        role="member",
        status="active",
    )
    db_session.add(member)
    await db_session.flush()
    from src.governance.workspaces import WorkspaceService, WorkspaceAccessDeniedError
    with pytest.raises(WorkspaceAccessDeniedError):
        await WorkspaceService().resolve_member(db_session, "open-u1")


@pytest.mark.asyncio
async def test_resolve_member_respects_inactive_member(db_session):
    """验证成员的 status 为非 active 时不被识别"""
    ws = Workspace(id="ws-active", name="活动空间", status="active")
    db_session.add(ws)
    await db_session.flush()
    member = WorkspaceMember(
        workspace_id="ws-active",
        open_userid="open-u1",
        role="member",
        status="suspended",
    )
    db_session.add(member)
    await db_session.flush()
    from src.governance.workspaces import WorkspaceService, WorkspaceAccessDeniedError
    with pytest.raises(WorkspaceAccessDeniedError):
        await WorkspaceService().resolve_member(db_session, "open-u1")
