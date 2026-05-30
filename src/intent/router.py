"""
意图路由器
规则优先 + LLM 回退的意图分类器，分析用户消息并确定意图和置信度

在总流程中的位置:
  用户消息（debug 或 wechat 端点）→ IntentRouter.route(message)
  → match_rules 规则匹配 → 匹配成功返回 (intent, 1.0)
                          → 匹配失败 → _llm_classify LLM 分类

Workflow:
  1. 空消息直接返回 unknown
  2. 规则匹配（确定性、低成本）
  3. 规则未命中时调用 LLM 分类（灵活性、处理自然语言变体）
  4. LLM 返回无效意图时降级为 unknown
"""
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
"""合法意图集合，LLM 返回不在此集合内的意图将降级为 unknown"""

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
    """意图路由器，规则匹配优先 + LLM 回退"""

    def __init__(self, llm_client: LLMClient):
        """初始化意图路由器

        参数:
            llm_client: LLM 客户端，用于规则未命中时的意图分类
        """
        self._llm = llm_client

    async def route(self, message: str) -> tuple[str, float]:
        """对用户消息进行意图分类

        先尝试规则匹配，匹配失败时调用 LLM 分类

        参数:
            message: 用户原始消息文本

        返回:
            tuple[str, float]: (意图标识, 置信度 0.0-1.0)
        """
        if not message or not message.strip():
            return ("unknown", 1.0)

        rule_match = match_rules(message)
        if rule_match is not None:
            return (rule_match, 1.0)

        return await self._llm_classify(message)

    async def _llm_classify(self, message: str) -> tuple[str, float]:
        """使用 LLM 进行意图分类（回退方案）

        参数:
            message: 用户原始消息文本

        返回:
            tuple[str, float]: (意图标识, 置信度 0.0-1.0)
            如果 LLM 返回无效意图，降级为 ("unknown", 0.0)
        """
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
