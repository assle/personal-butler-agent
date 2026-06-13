"""
权限引擎
提供结构化的权限判定，按规则优先级处理跨工作空间拒绝、首次使用审批、
高成本审批和授权放行。

Workflow:
1. ResearchSubmissionService 构造 PermissionRequest
2. PermissionEngine.evaluate() 按规则优先级判定
3. 返回 PermissionDecision 供调用方决定是否继续
"""
from dataclasses import dataclass
from enum import StrEnum


class PermissionEffect(StrEnum):
    """权限判定结果"""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class PermissionRequest:
    """权限判定输入"""

    operation: str
    role: str
    risk_level: str
    cost_class: str
    research_approved_once: bool
    workspace_matches: bool


@dataclass(frozen=True)
class PermissionDecision:
    """结构化权限判定"""

    effect: PermissionEffect
    policy_id: str
    reason: str


class PermissionEngine:
    """按规则优先级判定操作权限"""

    def evaluate(self, request: PermissionRequest) -> PermissionDecision:
        """按优先级执行权限规则

        参数:
            request: 权限判定输入

        返回:
            PermissionDecision: 结构化判定结果
        """
        # 规则 1: 跨工作空间操作始终拒绝
        if not request.workspace_matches:
            return PermissionDecision(
                effect=PermissionEffect.DENY,
                policy_id="workspace.boundary",
                reason="跨工作空间操作不被允许",
            )

        # 规则 2: 未注册的动态工具调用拒绝
        if request.risk_level == "external_action":
            return PermissionDecision(
                effect=PermissionEffect.DENY,
                policy_id="tool.unknown_dynamic",
                reason="未注册的动态工具调用不被允许",
            )

        # 规则 3: 首次研究需要审批
        if not request.research_approved_once:
            return PermissionDecision(
                effect=PermissionEffect.REQUIRE_APPROVAL,
                policy_id="research.first_use",
                reason="首次研究需要审批",
            )

        # 规则 4: 高成本操作需要审批
        if request.cost_class == "high":
            return PermissionDecision(
                effect=PermissionEffect.REQUIRE_APPROVAL,
                policy_id="cost.high_approval",
                reason="高成本操作需要审批",
            )

        # 规则 5: 已授权的只读和内部写入自动放行
        return PermissionDecision(
            effect=PermissionEffect.ALLOW,
            policy_id="default.authorized",
            reason="已授权的操作",
        )
