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

    # PostgreSQL 结构化数据库配置；生产 schema 由 Alembic 管理
    database_url: str = (
        "postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler"
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_require_migrations: bool = True

    # 首次迁移时用于承接现有单租户数据的默认工作空间
    default_workspace_id: str = "default"
    default_workspace_name: str = "Default Workspace"

    # 联网搜索配置；默认关闭，启用后由 search_web 工具查询实时信息
    web_search_enabled: bool = False
    web_search_provider: str = "tavily"
    web_search_api_key: str = ""
    web_search_max_results: int = 5
    web_search_timeout_seconds: int = 8

    # 天气查询配置；Open-Meteo 无需 API key，仅配置 HTTP 超时
    weather_timeout_seconds: int = 8

    # 企业微信智能机器人 URL 回调模式配置
    wecom_aibot_bot_id: str = ""
    wecom_aibot_token: str = ""
    wecom_aibot_encoding_aes_key: str = ""

    # 定时推送配置
    scheduler_targets_file: str = ""

    # 异步研究任务配置；默认关闭，启用时要求 Redis 和企微自建应用配置
    research_enabled: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"
    research_queue_name: str = "butler-research"
    research_max_rounds: int = 4
    research_timeout_seconds: int = 300
    # 研究预算与步骤控制
    research_max_steps: int = 12
    research_max_concurrent_steps: int = 3
    research_soft_token_budget: int = 15_000
    research_hard_token_budget: int = 20_000
    research_soft_cost_microunits: int = 350_000
    research_hard_cost_microunits: int = 500_000
    research_max_replans: int = 2
    research_max_repair_rounds: int = 1
    research_step_lease_seconds: int = 120
    research_high_cost_approval_microunits: int = 250_000
    # 研究可靠性配置
    research_circuit_failure_threshold: int = 3
    research_circuit_open_seconds: int = 60
    research_retry_base_seconds: float = 1.0
    research_retry_max_seconds: float = 30.0
    # 研究网页抓取配置
    research_web_fetch_timeout_seconds: int = 15
    research_web_max_response_bytes: int = 2_000_000
    research_web_max_redirects: int = 5
    research_web_max_pages_per_task: int = 20

    # MCP 研究工具适配器配置（默认关闭）
    research_mcp_enabled: bool = False
    research_mcp_config_file: str = ""

    # 企业微信自建应用主动私聊配置，与智能机器人回调配置相互独立
    wecom_app_corp_id: str = ""
    wecom_app_secret: str = ""
    wecom_app_agent_id: int = 0

    # 向量嵌入配置；DashScope API（Qwen3-Embedding），不配则使用本地哈希嵌入
    dashscope_api_key: str = ""


settings = Settings()
