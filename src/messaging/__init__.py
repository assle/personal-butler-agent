"""
消息场景分发包
集中管理入站消息规范化、群消息策略和私聊/群聊场景分发。
"""
from src.messaging.dispatch import DispatchResult, dispatch_message
from src.messaging.group_policy import (
    GroupPolicyDecision,
    apply_group_policy,
    classify_group_trigger,
)
from src.messaging.inbound import InboundMessage

__all__ = [
    "DispatchResult",
    "GroupPolicyDecision",
    "InboundMessage",
    "apply_group_policy",
    "classify_group_trigger",
    "dispatch_message",
]
