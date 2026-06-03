"""
配置模块测试
验证 Settings 类正确加载环境变量和使用默认值

测试范围:
  - 从环境变量加载所有配置字段
  - 未设置时使用合理的默认值
"""
import os
from unittest.mock import patch


def test_settings_loads_from_env():
    """验证 Settings 正确从环境变量加载所有字段

    模拟完整的环境变量，确保 Settings 构造函数能读取所有配置项。
    """
    env_vars = {
        "DEEPSEEK_API_KEY": "sk-test-key",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "DEEPSEEK_MODEL": "deepseek-chat",
        "DATABASE_URL": "sqlite+aiosqlite:///test.db",
        "WECOM_AIBOT_BOT_ID": "bot-1",
        "WECOM_AIBOT_TOKEN": "token-1",
        "WECOM_AIBOT_ENCODING_AES_KEY": "aes-key-1",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert settings.deepseek_api_key == "sk-test-key"
        assert settings.deepseek_base_url == "https://api.deepseek.com"
        assert settings.deepseek_model == "deepseek-chat"
        assert settings.database_url == "sqlite+aiosqlite:///test.db"
        assert settings.wecom_aibot_bot_id == "bot-1"
        assert settings.wecom_aibot_token == "token-1"
        assert settings.wecom_aibot_encoding_aes_key == "aes-key-1"


def test_settings_use_defaults():
    """验证 Settings 在缺少可选环境变量时使用默认值

    仅设置必需的 DEEPSEEK_API_KEY，验证其他字段回退到类定义中的默认值。
    """
    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert settings.deepseek_base_url == "https://api.deepseek.com"
        assert settings.deepseek_model == "deepseek-chat"
        assert settings.database_url == "sqlite+aiosqlite:///butler.db"
        assert settings.wecom_aibot_bot_id == ""
        assert settings.wecom_aibot_token == ""
        assert settings.wecom_aibot_encoding_aes_key == ""


def test_settings_loads_web_search_from_env():
    """验证 Settings 正确从环境变量加载联网搜索配置

    模拟 Tavily 搜索相关环境变量，确保 Settings 构造函数能读取启用状态、供应商、密钥和限制参数。
    """
    env_vars = {
        "DEEPSEEK_API_KEY": "sk-test-key",
        "WEB_SEARCH_ENABLED": "true",
        "WEB_SEARCH_PROVIDER": "tavily",
        "WEB_SEARCH_API_KEY": "tvly-test",
        "WEB_SEARCH_MAX_RESULTS": "3",
        "WEB_SEARCH_TIMEOUT_SECONDS": "6",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert settings.web_search_enabled is True
        assert settings.web_search_provider == "tavily"
        assert settings.web_search_api_key == "tvly-test"
        assert settings.web_search_max_results == 3
        assert settings.web_search_timeout_seconds == 6


def test_settings_web_search_use_defaults():
    """验证联网搜索配置默认关闭并使用安全默认值

    仅设置必需的 DEEPSEEK_API_KEY，验证联网搜索默认不启用且 Tavily 参数使用类定义中的默认值。
    """
    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert settings.web_search_enabled is False
        assert settings.web_search_provider == "tavily"
        assert settings.web_search_api_key == ""
        assert settings.web_search_max_results == 5
        assert settings.web_search_timeout_seconds == 8


def test_legacy_self_built_app_env_is_ignored():
    """验证旧自建应用环境变量不再被 Settings 暴露

    旧的 WECHAT_* 回调配置和 WECOM_CORP_* 服务端 API 配置已删除，
    避免误以为智能机器人 URL 回调需要自建应用 Secret。
    """
    env_vars = {
        "DEEPSEEK_API_KEY": "sk-test-key",
        "WECHAT_CORP_ID": "ww-legacy",
        "WECHAT_TOKEN": "legacy-token",
        "WECHAT_ENCODING_AES_KEY": "legacy-aes-key",
        "WECOM_CORP_ID": "ww-corp",
        "WECOM_CORP_SECRET": "corp-secret",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert not hasattr(settings, "wechat_corp_id")
        assert not hasattr(settings, "wechat_token")
        assert not hasattr(settings, "wechat_encoding_aes_key")
        assert not hasattr(settings, "wecom_corp_id")
        assert not hasattr(settings, "wecom_corp_secret")
