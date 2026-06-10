"""
群聊 @ 分类器
规则优先识别群聊总结、天气查询、简单问答和不支持能力。
"""
from __future__ import annotations

import json

SUMMARY_KEYWORDS = ("总结", "摘要", "概括", "汇总")
WEATHER_KEYWORDS = ("天气", "气温", "下雨", "降雨")
BLOCKED_KEYWORDS = ("训练", "打卡", "练什么", "食谱", "吃什么", "饮食", "餐")
QUESTION_MARKERS = ("?", "？", "吗", "怎么", "如何", "为什么", "什么")
ALLOWED_CATEGORIES = {
    "summarize_group",
    "weather",
    "simple_qa",
    "unsupported",
}

CLASSIFIER_PROMPT = """你是群聊机器人意图分类器。只允许返回以下类别：
- summarize_group: 用户要求总结群聊
- weather: 用户询问天气、气温、下雨等
- simple_qa: 简单问题或轻量问答
- unsupported: 训练、食谱、私密陪伴、复杂任务或无法判断

只返回 JSON：
{"category": "<category>"}"""


def classify_group_message_by_rules(message: str) -> str | None:
    """用确定性规则识别群聊消息类别

    参数:
        message: 群聊消息文本

    返回:
        str | None: 类别；规则未命中返回 None
    """
    normalized = message.strip().lower()
    if not normalized:
        return "unsupported"
    if any(keyword in normalized for keyword in SUMMARY_KEYWORDS):
        return "summarize_group"
    if any(keyword in normalized for keyword in WEATHER_KEYWORDS):
        return "weather"
    if any(keyword in normalized for keyword in BLOCKED_KEYWORDS):
        return "unsupported"
    if any(marker in normalized for marker in QUESTION_MARKERS):
        return "simple_qa"
    return None


async def classify_group_message(message: str, llm_client) -> str:
    """规则优先、LLM 兜底分类群聊 @ 消息

    参数:
        message: 群聊消息文本
        llm_client: LLM 客户端，用于规则未命中时分类

    返回:
        str: 群聊场景类别
    """
    rule_match = classify_group_message_by_rules(message)
    if rule_match is not None:
        return rule_match
    try:
        raw = await llm_client.chat_json(
            messages=[
                {"role": "system", "content": CLASSIFIER_PROMPT},
                {"role": "user", "content": message},
            ],
        )
        category = json.loads(raw).get("category", "unsupported")
        if category in ALLOWED_CATEGORIES:
            return category
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return "unsupported"
