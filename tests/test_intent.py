import pytest


class TestIntentRules:
    def test_match_log_training_by_keyword(self):
        from src.intent.rules import match_rules

        assert match_rules("打卡 今天练了胸") == "log_training"
        assert match_rules("记录训练 卧推") == "log_training"

    def test_match_today_plan_by_keyword(self):
        from src.intent.rules import match_rules

        assert match_rules("今天练什么") == "today_plan"
        assert match_rules("给我训练建议") == "today_plan"

    def test_match_summarize_text_by_keyword(self):
        from src.intent.rules import match_rules

        assert match_rules("帮我总结一下这段聊天") == "summarize_text"
        assert match_rules("summary of the chat") == "summarize_text"

    def test_match_make_meal_plan_by_keyword(self):
        from src.intent.rules import match_rules

        assert match_rules("今天吃什么") == "make_meal_plan"
        assert match_rules("给我做一个meal plan") == "make_meal_plan"

    def test_no_match_returns_none(self):
        from src.intent.rules import match_rules

        assert match_rules("你好") is None
        assert match_rules("今天天气怎么样") is None
        assert match_rules("") is None


from unittest.mock import AsyncMock, patch


class TestIntentRouter:
    @pytest.mark.asyncio
    async def test_rule_match_skips_llm(self):
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("打卡 今天练了胸")
        assert intent == "log_training"
        assert confidence == 1.0
        mock_llm.chat_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_fallback_when_no_rule_match(self):
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
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        mock_llm.chat_json.return_value = '{"intent": "some_fake_intent", "confidence": 0.5}'
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("blah blah")
        assert intent == "unknown"
        assert confidence == 0.5

    @pytest.mark.asyncio
    async def test_empty_message_returns_unknown(self):
        from src.intent.router import IntentRouter

        mock_llm = AsyncMock()
        router = IntentRouter(llm_client=mock_llm)
        intent, confidence = await router.route("")
        assert intent == "unknown"
        assert confidence == 1.0
        mock_llm.chat_json.assert_not_called()
