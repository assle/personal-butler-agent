"""
工作空间成员解析服务
根据企业微信 open_userid 解析用户的工作空间身份，处理多工作空间情况

Workflow:
1. PrivateButlerAgent 接收研究提交请求
2. ResearchSubmissionService 调用 WorkspaceService.resolve_member()
3. 解析成功返回 WorkspaceContext，注入到 ResearchTaskService.create_task()
4. 解析失败抛出 WorkspaceAccessDeniedError 或 AmbiguousWorkspaceError
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.models.workspace import Workspace, WorkspaceMember


class WorkspaceAccessDeniedError(RuntimeError):
    """用户对指定工作空间无访问权限"""


class AmbiguousWorkspaceError(RuntimeError):
    """用户属于多个工作空间，必须显式选择"""


@dataclass(frozen=True)
class WorkspaceContext:
    """已验证的工作空间成员上下文

    字段:
        workspace_id: 工作空间 ID
        member_id: 成员记录唯一标识
        open_userid: 企业微信用户标识
        role: 成员角色
        research_approved_once: 是否已完成首次研究审批
    """

    workspace_id: str
    member_id: int
    open_userid: str
    role: str
    research_approved_once: bool


class WorkspaceService:
    """解析并验证企业微信用户的工作空间身份"""

    async def resolve_member(
        self,
        db: AsyncSession,
        open_userid: str,
        workspace_id: str | None = None,
    ) -> WorkspaceContext:
        """解析活动成员身份

        参数:
            db: 异步数据库会话
            open_userid: 企业微信机器人用户标识
            workspace_id: 可选的显式工作空间 ID，用于消除多工作空间歧义

        返回:
            WorkspaceContext: 已验证的工作空间上下文

        异常:
            WorkspaceAccessDeniedError: 用户不属于任何活动工作空间
            AmbiguousWorkspaceError: 用户属于多个工作空间且未指定 workspace_id
        """
        query = (
            select(WorkspaceMember)
            .join(Workspace, WorkspaceMember.workspace_id == Workspace.id)
            .where(
                WorkspaceMember.open_userid == open_userid,
                WorkspaceMember.status == "active",
                Workspace.status == "active",
            )
        )
        if workspace_id is not None:
            query = query.where(WorkspaceMember.workspace_id == workspace_id)

        result = await db.execute(query)
        members = result.scalars().all()

        if not members:
            raise WorkspaceAccessDeniedError(
                f"用户 {open_userid} 不属于任何活动工作空间"
            )

        if workspace_id is not None:
            member = members[0]
            return WorkspaceContext(
                workspace_id=member.workspace_id,
                member_id=member.id,
                open_userid=member.open_userid,
                role=member.role,
                research_approved_once=member.research_approved_once,
            )

        if len(members) > 1:
            raise AmbiguousWorkspaceError(
                f"用户 {open_userid} 属于 {len(members)} 个工作空间，"
                f"请指定 workspace_id"
            )

        member = members[0]
        return WorkspaceContext(
            workspace_id=member.workspace_id,
            member_id=member.id,
            open_userid=member.open_userid,
            role=member.role,
            research_approved_once=member.research_approved_once,
        )
