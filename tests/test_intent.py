"""
意图路由模块测试
验证规则匹配和 LLM 回退分类的正确性

测试范围:
  - 关键词规则匹配（确定性）
  - LLM 回退分类（规则未命中时）
  - unknown 降级（无效意图/空消息）
"""
import pytest


class TestIntentRules:
    """意图规则匹配单元测试"""

    def test_match_log_training_by_keyword(self):
        """验证"打卡"和"训练"关键词匹配 log_training 意图"""
        from src.intent.rules import match_rules

        assert match_rules("打卡 今天练了胸") == "log_training"
        assert match_rules("记录训练 卧推") == "log_training"

    def test_match_today_plan_by_keyword(self):
        """验证"今天练什么"和"训练建议"匹配 today_plan 意图"""
        from src.intent.rules import match_rules

        assert match_rules("今天练什么") == "today_plan"
        assert match_rules("给我训练建议") == "today_plan"

    def test_match_summarize_text_by_keyword(self):
        """验证"总结"和"summary"匹配 summarize_text 意图"""
        from src.intent.rules import match_rules

        assert match_rules("帮我总结一下这段聊天") == "summarize_text"
        assert match_rules("summary of the chat") == "summarize_text"

    def test_match_make_meal_plan_by_keyword(self):
        """验证"吃什么"和"meal plan"匹配 make_meal_plan 意图"""
        from src.intent.rules import match_rules

        assert match_rules("今天吃什么") == "make_meal_plan"
        assert match_rules("给我做一个meal plan") == "make_meal_plan"

    def test_no_match_returns_none(self):
        """验证无关键词匹配时返回 None（触发 LLM 分类）"""
        from src.intent.rules import match_rules

        assert match_rules("随便聊聊") is None
        assert match_rules("今天天气怎么样") is None
        assert match_rules("") is None


from unittest.mock import AsyncMock, patch


class TestIntentRouter:
    """意图路由器集成测试（规则 + LLM 回退）"""

    @pytest.mark.asyncio
    async def test_rule_match_skips_llm(self):
        """验证规则匹配成功时跳过 LLM 调用

        消息包含"打卡"关键词 → 直接返回 log_training，不调用 chat_json。
        """
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("打卡 今天练了胸")
        assert intent == "log_training"
        assert confidence == 1.0
        mock_llm.chat_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_fallback_when_no_rule_match(self):
        """验证规则未命中时调用 LLM 分类

        消息无关键词 → chat_json 被调用 → 使用 LLM 返回的意图。
        """
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        mock_llm.chat_json.return_value = '{"intent": "qa", "confidence": 0.85}'
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("今天天气怎么样")
        assert intent == "qa"
        assert confidence == 0.85
        mock_llm.chat_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_unknown_intent_falls_back_to_unknown(self):
        """验证 LLM 返回无效意图时降级为 unknown

        LLM 返回不在 KNOWN_INTENTS 中的意图 → 强制转为 unknown。
        """
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        mock_llm.chat_json.return_value = '{"intent": "some_fake_intent", "confidence": 0.5}'
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("blah blah")
        assert intent == "unknown"
        assert confidence == 0.5

    @pytest.mark.asyncio
    async def test_empty_message_returns_unknown(self):
        """验证空消息直接返回 unknown，不调用 LLM"""
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("")
        assert intent == "unknown"
        assert confidence == 1.0
        mock_llm.chat_json.assert_not_called()
