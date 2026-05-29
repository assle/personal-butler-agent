from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.intent.rules import match_rules

if TYPE_CHECKING:
    from src.llm.client import LLMClient

KNOWN_INTENTS = {
    "log_training",
    "today_plan",
    "summarize_text",
    "make_meal_plan",
    "qa",
    "unknown",
}

SYSTEM_PROMPT = """你是一个意图分类器。分析用户消息，返回以下意图之一：

- log_training: 用户想记录训练数据（打卡、记录训练内容）
- today_plan: 用户想获取今日训练计划建议
- summarize_text: 用户想总结一段文本/聊天记录
- make_meal_plan: 用户想要食谱/饮食计划
- qa: 一般性问题或对话
- unknown: 无法识别的消息

只返回 JSON，不要有其他文字：
{"intent": "<intent>", "confidence": <0.0-1.0>}"""


class IntentRouter:
    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def route(self, message: str) -> tuple[str, float]:
        if not message or not message.strip():
            return ("unknown", 1.0)

        rule_match = match_rules(message)
        if rule_match is not None:
            return (rule_match, 1.0)

        return await self._llm_classify(message)

    async def _llm_classify(self, message: str) -> tuple[str, float]:
        try:
            raw = await self._llm.chat_json(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
            )
            result = json.loads(raw)
            intent = result.get("intent", "unknown")
            if intent not in KNOWN_INTENTS:
                intent = "unknown"
            confidence = float(result.get("confidence", 0.0))
            return (intent, confidence)
        except (json.JSONDecodeError, KeyError, ValueError):
            return ("unknown", 0.0)
