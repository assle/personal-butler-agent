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
