"""
意图路由规则模块
定义确定性关键词匹配规则，对高频消息类型做快速意图判定

在总流程中的位置:
  IntentRouter.route() 首先调用 match_rules() 尝试规则匹配
  匹配成功 → 直接返回意图（低成本、可测试）
  匹配失败 → 降级到 LLM 分类（灵活、处理自然语言变体）

Workflow:
  用户消息 → match_rules → 遍历 RULES 列表 → 关键词命中返回 intent
                                                     未命中返回 None → LLM 分类
"""
from dataclasses import dataclass


@dataclass
class IntentRule:
    """意图匹配规则，包含意图标识和触发关键词列表"""

    intent: str
    """意图标识字符串"""

    keywords: list[str]
    """触发关键词列表，任意一个命中即匹配"""


RULES: list[IntentRule] = [
    IntentRule(
        "today_plan",
        ["今天练什么", "今日计划", "训练建议"],
    ),
    IntentRule(
        "log_training",
        ["打卡", "记录训练", "练了", "训练"],
    ),
    IntentRule(
        "summarize_text",
        ["总结", "summary", "帮我总结"],
    ),
    IntentRule(
        "make_meal_plan",
        ["食谱", "吃什么", "meal plan", "饮食"],
    ),
]
"""规则列表，按顺序匹配，先匹配到的规则生效"""


def match_rules(message: str) -> str | None:
    """对用户消息进行关键词规则匹配

    参数:
        message: 用户原始消息文本

    返回:
        str | None: 匹配到的意图标识，未匹配返回 None（触发 LLM 分类）
    """
    if not message or not message.strip():
        return None
    message_lower = message.lower()
    for rule in RULES:
        for keyword in rule.keywords:
            if keyword.lower() in message_lower:
                return rule.intent
    return None
