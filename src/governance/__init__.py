"""
治理模块
提供工作空间解析、权限判定和研究生命周期 Hook 基础设施

在总流程中的位置:
  research/submission.py 在创建研究任务前调用 WorkspaceService 验证成员身份
  research/service.py 在任务持久化时写入 workspace_id
"""
from src.governance.hooks import (
    CriticalHookError,
    HookBus,
    HookEvent,
)
from src.governance.permissions import (
    PermissionDecision,
    PermissionEffect,
    PermissionEngine,
    PermissionRequest,
)
from src.governance.workspaces import (
    AmbiguousWorkspaceError,
    WorkspaceAccessDeniedError,
    WorkspaceContext,
    WorkspaceService,
)

__all__ = [
    "AmbiguousWorkspaceError",
    "CriticalHookError",
    "HookBus",
    "HookEvent",
    "PermissionDecision",
    "PermissionEffect",
    "PermissionEngine",
    "PermissionRequest",
    "WorkspaceAccessDeniedError",
    "WorkspaceContext",
    "WorkspaceService",
]
