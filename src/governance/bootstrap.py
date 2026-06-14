"""默认工作空间启动引导，负责幂等创建空间和显式配置的管理员成员。

Workflow:
1. FastAPI 完成数据库结构检查。
2. 按配置确保默认工作空间存在。
3. 若配置 owner open_userid，则确保对应活动 owner 成员存在。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.workspace import Workspace, WorkspaceMember


async def ensure_default_workspace(
    db: AsyncSession,
    *,
    workspace_id: str,
    workspace_name: str,
    owner_open_userid: str,
) -> None:
    """幂等创建默认空间及 owner；参数为会话和引导配置；无返回值。"""
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        db.add(
            Workspace(
                id=workspace_id,
                name=workspace_name,
                status="active",
                policy={},
            )
        )
        await db.flush()

    normalized_owner = owner_open_userid.strip()
    if not normalized_owner:
        return

    member = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.open_userid == normalized_owner,
        )
    )
    if member is None:
        db.add(
            WorkspaceMember(
                workspace_id=workspace_id,
                open_userid=normalized_owner,
                role="owner",
                status="active",
                research_approved_once=False,
            )
        )
        await db.flush()
