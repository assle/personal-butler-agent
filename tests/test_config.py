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
    }
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings()
        assert settings.deepseek_api_key == "sk-test-key"
        assert settings.deepseek_base_url == "https://api.deepseek.com"
        assert settings.deepseek_model == "deepseek-chat"
        assert settings.database_url == "sqlite+aiosqlite:///test.db"


def test_settings_use_defaults():
    """验证 Settings 在缺少可选环境变量时使用默认值

    仅设置必需的 DEEPSEEK_API_KEY，验证其他字段回退到类定义中的默认值。
    """
    env_vars = {"DEEPSEEK_API_KEY": "sk-test-key"}
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings()
        assert settings.deepseek_base_url == "https://api.deepseek.com"
        assert settings.deepseek_model == "deepseek-chat"
        assert settings.database_url == "sqlite+aiosqlite:///butler.db"
