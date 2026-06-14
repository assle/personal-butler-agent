"""默认工作空间引导测试，验证启动初始化可安全重复执行。"""

from sqlalchemy import func, select

from src.models.workspace import Workspace, WorkspaceMember


async def test_bootstrap_creates_default_workspace_and_owner(db_session) -> None:
    """验证空数据库创建默认空间和 owner；参数为测试会话；无返回值。"""
    from src.governance.bootstrap import ensure_default_workspace

    await ensure_default_workspace(
        db_session,
        workspace_id="default",
        workspace_name="Default Workspace",
        owner_open_userid="LuZhenDong",
    )
    await db_session.commit()

    workspace = await db_session.get(Workspace, "default")
    member = await db_session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == "default",
            WorkspaceMember.open_userid == "LuZhenDong",
        )
    )

    assert workspace is not None
    assert workspace.name == "Default Workspace"
    assert workspace.status == "active"
    assert member is not None
    assert member.role == "owner"
    assert member.status == "active"


async def test_bootstrap_is_idempotent(db_session) -> None:
    """验证重复初始化不会产生重复记录；参数为测试会话；无返回值。"""
    from src.governance.bootstrap import ensure_default_workspace

    for _ in range(2):
        await ensure_default_workspace(
            db_session,
            workspace_id="default",
            workspace_name="Default Workspace",
            owner_open_userid="LuZhenDong",
        )
        await db_session.commit()

    workspace_count = await db_session.scalar(select(func.count()).select_from(Workspace))
    member_count = await db_session.scalar(
        select(func.count()).select_from(WorkspaceMember)
    )

    assert workspace_count == 1
    assert member_count == 1


async def test_bootstrap_without_owner_only_creates_workspace(db_session) -> None:
    """验证未配置 owner 时不自动授权用户；参数为测试会话；无返回值。"""
    from src.governance.bootstrap import ensure_default_workspace

    await ensure_default_workspace(
        db_session,
        workspace_id="default",
        workspace_name="Default Workspace",
        owner_open_userid="",
    )
    await db_session.commit()

    workspace_count = await db_session.scalar(select(func.count()).select_from(Workspace))
    member_count = await db_session.scalar(
        select(func.count()).select_from(WorkspaceMember)
    )

    assert workspace_count == 1
    assert member_count == 0
