from dataclasses import dataclass


@dataclass
class IntentRule:
    intent: str
    keywords: list[str]


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


def match_rules(message: str) -> str | None:
    if not message or not message.strip():
        return None
    message_lower = message.lower()
    for rule in RULES:
        for keyword in rule.keywords:
            if keyword.lower() in message_lower:
                return rule.intent
    return None
