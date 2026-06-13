"""
权限引擎测试
验证 PermissionEngine 按规则优先级做出正确的权限判定
"""
from src.governance.permissions import (
    PermissionEffect,
    PermissionEngine,
    PermissionRequest,
)


def test_permission_engine_requires_first_use_approval():
    """验证首次研究需要审批"""
    decision = PermissionEngine().evaluate(
        PermissionRequest(
            operation="research.plan.execute",
            role="member",
            risk_level="internal_write",
            cost_class="medium",
            research_approved_once=False,
            workspace_matches=True,
        )
    )
    assert decision.effect == PermissionEffect.REQUIRE_APPROVAL
    assert decision.policy_id == "research.first_use"


def test_permission_engine_denies_cross_workspace():
    """验证跨工作空间操作始终拒绝"""
    decision = PermissionEngine().evaluate(
        PermissionRequest(
            operation="research.evidence.read",
            role="admin",
            risk_level="read",
            cost_class="low",
            research_approved_once=True,
            workspace_matches=False,
        )
    )
    assert decision.effect == PermissionEffect.DENY


def test_permission_engine_allows_authorized_read():
    """验证已审批用户在匹配工作空间内的只读操作自动放行"""
    decision = PermissionEngine().evaluate(
        PermissionRequest(
            operation="research.evidence.read",
            role="member",
            risk_level="read",
            cost_class="low",
            research_approved_once=True,
            workspace_matches=True,
        )
    )
    assert decision.effect == PermissionEffect.ALLOW


def test_permission_engine_allows_authorized_internal_write():
    """验证已审批用户在匹配工作空间内的内部写入自动放行"""
    decision = PermissionEngine().evaluate(
        PermissionRequest(
            operation="research.plan.execute",
            role="member",
            risk_level="internal_write",
            cost_class="medium",
            research_approved_once=True,
            workspace_matches=True,
        )
    )
    assert decision.effect == PermissionEffect.ALLOW


def test_permission_engine_requires_approval_for_high_cost():
    """验证高成本操作需要审批"""
    decision = PermissionEngine().evaluate(
        PermissionRequest(
            operation="research.evidence.fetch",
            role="member",
            risk_level="internal_write",
            cost_class="high",
            research_approved_once=True,
            workspace_matches=True,
        )
    )
    assert decision.effect == PermissionEffect.REQUIRE_APPROVAL
    assert decision.policy_id == "cost.high_approval"


def test_permission_engine_denies_unknown_tool():
    """验证未注册的动态工具调用被拒绝"""
    decision = PermissionEngine().evaluate(
        PermissionRequest(
            operation="tool.dynamic.execute",
            role="member",
            risk_level="external_action",
            cost_class="unknown",
            research_approved_once=True,
            workspace_matches=True,
        )
    )
    assert decision.effect == PermissionEffect.DENY
