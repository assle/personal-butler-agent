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
        assert settings.database_url == "postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler"
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


def test_settings_loads_research_and_wecom_app_config():
    """验证研究队列和企微自建应用配置可从环境变量加载"""
    env_vars = {
        "DEEPSEEK_API_KEY": "sk-test-key",
        "RESEARCH_ENABLED": "true",
        "REDIS_URL": "redis://redis.test:6379/2",
        "RESEARCH_QUEUE_NAME": "butler-research-test",
        "RESEARCH_MAX_ROUNDS": "4",
        "RESEARCH_TIMEOUT_SECONDS": "300",
        "WECOM_APP_CORP_ID": "ww-test",
        "WECOM_APP_SECRET": "secret-test",
        "WECOM_APP_AGENT_ID": "1000002",
        "WECOM_APP_CALLBACK_TOKEN": "callback-token",
        "WECOM_APP_CALLBACK_ENCODING_AES_KEY": "callback-aes-key",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert settings.research_enabled is True
        assert settings.redis_url == "redis://redis.test:6379/2"
        assert settings.research_queue_name == "butler-research-test"
        assert settings.research_max_rounds == 4
        assert settings.research_timeout_seconds == 300
        assert settings.wecom_app_corp_id == "ww-test"
        assert settings.wecom_app_secret == "secret-test"
        assert settings.wecom_app_agent_id == 1000002
        assert settings.wecom_app_callback_token == "callback-token"
        assert settings.wecom_app_callback_encoding_aes_key == "callback-aes-key"


def test_settings_research_defaults_are_disabled():
    """验证未配置 Redis 和自建应用时研究功能默认关闭"""
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-key"}, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert settings.research_enabled is False
        assert settings.redis_url == "redis://127.0.0.1:6379/0"
        assert settings.research_queue_name == "butler-research"
        assert settings.research_max_rounds == 4
        assert settings.research_timeout_seconds == 300
        assert settings.wecom_app_corp_id == ""
        assert settings.wecom_app_secret == ""
        assert settings.wecom_app_agent_id == 0
        assert settings.wecom_app_callback_token == ""
        assert settings.wecom_app_callback_encoding_aes_key == ""


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


def test_settings_default_database_url_is_postgresql():
    """验证团队部署默认数据库切换为 PostgreSQL"""
    with patch.dict(
        os.environ,
        {"DEEPSEEK_API_KEY": "test"},
        clear=True,
    ):
        from src.config import Settings

        settings = Settings(_env_file=None)
    assert settings.database_url == (
        "postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler"
    )
    assert settings.database_pool_size == 10
    assert settings.database_max_overflow == 20
    assert settings.database_require_migrations is True


def test_settings_loads_workspace_bootstrap_config():
    """验证默认工作空间迁移配置可从环境变量加载"""
    env = {
        "DEEPSEEK_API_KEY": "test",
        "DEFAULT_WORKSPACE_ID": "ws-internal",
        "DEFAULT_WORKSPACE_NAME": "Internal Research",
        "DEFAULT_WORKSPACE_OWNER_OPEN_USERID": "owner-open-userid",
    }
    with patch.dict(os.environ, env, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
    assert settings.default_workspace_id == "ws-internal"
    assert settings.default_workspace_name == "Internal Research"
    assert settings.default_workspace_owner_open_userid == "owner-open-userid"
