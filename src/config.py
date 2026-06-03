"""
应用配置管理
从 .env 文件加载所有运行时配置，包括 LLM、数据库和企业微信相关参数

Workflow:
1. Settings 类通过 pydantic-settings 自动从 .env 文件加载环境变量
2. 未配置的字段使用空字符串默认值，避免应用启动失败
3. 全局 settings 实例在模块加载时创建，供所有模块导入使用
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置类，所有字段从 .env 文件自动加载"""
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # DeepSeek LLM 配置
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # SQLite 数据库配置
    database_url: str = "sqlite+aiosqlite:///butler.db"

    # 联网搜索配置；默认关闭，启用后由 search_web 工具查询实时信息
    web_search_enabled: bool = False
    web_search_provider: str = "tavily"
    web_search_api_key: str = ""
    web_search_max_results: int = 5
    web_search_timeout_seconds: int = 8

    # 企业微信智能机器人 URL 回调模式配置
    wecom_aibot_bot_id: str = ""
    wecom_aibot_token: str = ""
    wecom_aibot_encoding_aes_key: str = ""

    # 兼容旧长连接配置；URL 回调模式不再使用该字段
    wecom_aibot_secret: str = ""

    # 定时推送配置
    scheduler_cron: str = "0 9 * * *"
    scheduler_target_type: str = "single"
    scheduler_target_id: str = ""
    scheduler_message: str = "今日训练建议"
    scheduler_intent: str = "today_plan"


settings = Settings()
