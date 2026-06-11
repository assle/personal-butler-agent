"""
Personal Butler Agent 应用入口
负责 FastAPI 应用初始化、单例组件创建和路由注册

Workflow:
1. 创建 LLMClient、知识库/提醒等服务和 scene agent 单例
2. 私聊、群聊 @、scheduler webhook 分别由场景 agent 处理
3. lifespan 中初始化数据库表结构
4. 注册智能机器人 URL 回调路由
5. 配置企业微信群 webhook 定时推送
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import settings
from src.llm.client import LLMClient
from src.agents.summary import SummaryAgent
from src.agents.group_mention import GroupMentionAgent
from src.agents.poll import PollAgent
from src.agents.private_butler import PrivateButlerAgent
from src.agents.reminder import ReminderAgent
from src.agents.webhook_composer import WebhookComposerAgent
from src.knowledge import KnowledgeService
from src.reminders import ReminderService
from src.search import WebSearchService
from src.weather import WeatherService
from src.scheduler import SchedulerManager, WebhookPushClient, load_webhook_targets

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)

llm_client = LLMClient()
reminder_service = ReminderService([])
summary_agent = SummaryAgent(llm_client=llm_client)
knowledge_service = KnowledgeService()
web_search_service = WebSearchService()
weather_service = WeatherService()
reminder_agent = ReminderAgent(
    llm_client=llm_client,
    reminder_service=reminder_service,
)
private_butler_agent = PrivateButlerAgent(
    llm_client=llm_client,
    summary_agent=summary_agent,
    knowledge_service=knowledge_service,
    web_search_service=web_search_service,
    weather_service=weather_service,
    reminder_agent=reminder_agent,
)
# 模块级别：先创建 PollAgent（scheduler 尚未就绪，传 None）
poll_agent = PollAgent(
    llm_client=llm_client,
    scheduler_manager=None,
    webhook_client=None,
)
group_mention_agent = GroupMentionAgent(
    llm_client=llm_client,
    summary_agent=summary_agent,
    weather_service=weather_service,
    poll_agent=poll_agent,
)
webhook_composer_agent = WebhookComposerAgent(
    llm_client=llm_client,
    weather_service=weather_service,
)

scheduler_manager: SchedulerManager | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理

    应用启动时自动创建数据库表结构，并按配置启动群 webhook 定时推送。

    参数:
        app: FastAPI 应用实例
    """
    from src.db.base import Base
    from src.db.session import async_session, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    global scheduler_manager

    if settings.scheduler_targets_file:
        webhook_targets = load_webhook_targets(settings.scheduler_targets_file)
        reminder_service.set_targets(webhook_targets)
        scheduler_manager = SchedulerManager(
            db_session_factory=async_session,
            webhook_composer_agent=webhook_composer_agent,
            webhook_client=WebhookPushClient(),
            webhook_targets=webhook_targets,
            weather_service=weather_service,
            enable_reminder_scan=True,
        )
        scheduler_manager.start()
        # scheduler_manager 就绪后，注入到 PollAgent
        poll_agent._scheduler_manager = scheduler_manager
        poll_agent._webhook_client = WebhookPushClient()

    yield

    if scheduler_manager is not None:
        scheduler_manager.shutdown()
    await engine.dispose()


app = FastAPI(title="Personal Butler Agent", version="0.1.0", lifespan=lifespan)

# 智能机器人 URL 回调路由（Token + EncodingAESKey 配置完整时注册）
if settings.wecom_aibot_token and settings.wecom_aibot_encoding_aes_key:
    from src.db.session import async_session
    from src.wechat.callback_router import create_aibot_callback_router

    app.include_router(
        create_aibot_callback_router(
            token=settings.wecom_aibot_token,
            encoding_aes_key=settings.wecom_aibot_encoding_aes_key,
            receive_id=settings.wecom_aibot_bot_id,
            private_agent=private_butler_agent,
            group_agent=group_mention_agent,
            db_session_factory=async_session,
        )
    )
    logger.info("AIBot callback route: registered")
