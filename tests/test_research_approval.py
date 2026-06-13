"""研究审批测试"""
import pytest
from src.research.approvals import ApprovalPolicy


def test_first_use_or_high_cost_requires_approval():
    """验证首次或高成本计划需要审批"""
    policy = ApprovalPolicy(high_cost_microunits=250_000)
    assert policy.evaluate(first_use=True, estimated_cost=1) is True
    assert policy.evaluate(first_use=False, estimated_cost=250_001) is True
    assert policy.evaluate(first_use=False, estimated_cost=10) is False
    assert policy.evaluate(first_use=False, estimated_cost=250_000) is False
