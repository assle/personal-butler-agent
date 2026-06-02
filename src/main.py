"""
Personal Butler Agent 应用入口
负责 FastAPI 应用初始化、单例组件创建和路由注册

Workflow:
1. 创建 LLMClient、IntentRouter、各业务 agent 单例
2. 向 AgentRegistry 注册所有 intent → agent 映射
3. lifespan 中初始化数据库表结构
4. 注册调试路由和智能机器人 URL 回调路由
5. URL 回调模式不再启动 WebSocket 长连接客户端
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import settings
from src.llm.client import LLMClient
from src.intent.router import IntentRouter
from src.agents.fitness import FitnessAgent
from src.agents.summary import SummaryAgent
from src.agents.meal import MealAgent
from src.agents.qa import QAAgent
from src.agents.registry import AgentRegistry
from src.router.debug import create_debug_router

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)

llm_client = LLMClient()
intent_router = IntentRouter(llm_client=llm_client)
fitness_agent = FitnessAgent(llm_client=llm_client)
summary_agent = SummaryAgent(llm_client=llm_client)
meal_agent = MealAgent(llm_client=llm_client)
qa_agent = QAAgent(llm_client=llm_client)

agent_registry = AgentRegistry()
agent_registry.register("log_training", fitness_agent)
agent_registry.register("today_plan", fitness_agent)
agent_registry.register("summarize_text", summary_agent)
agent_registry.register("summarize_group", summary_agent)
agent_registry.register("make_meal_plan", meal_agent)
agent_registry.register("qa", qa_agent)
agent_registry.register("unknown", qa_agent)
agent_registry.set_fallback(qa_agent)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理

    应用启动时自动创建数据库表结构。URL 回调模式下不再启动 WebSocket 长连接。

    参数:
        app: FastAPI 应用实例
    """
    from src.db.base import Base
    from src.db.session import engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if settings.wecom_aibot_secret:
        logger.warning("WECOM_AIBOT_SECRET is ignored in URL callback mode")
    if settings.scheduler_cron and settings.scheduler_target_id:
        logger.warning("Scheduler push is disabled in URL callback mode because WebSocket is not started")

    yield

    await engine.dispose()


app = FastAPI(title="Personal Butler Agent", version="0.1.0", lifespan=lifespan)

# 调试路由（始终注册，用于本地开发测试）
debug_router = create_debug_router(
    intent_router=intent_router,
    agent_registry=agent_registry,
)
app.include_router(debug_router)

# 智能机器人 URL 回调路由（Token + EncodingAESKey 配置完整时注册）
if settings.wecom_aibot_token and settings.wecom_aibot_encoding_aes_key:
    from src.db.session import async_session
    from src.wechat.callback_router import create_aibot_callback_router

    app.include_router(
        create_aibot_callback_router(
            token=settings.wecom_aibot_token,
            encoding_aes_key=settings.wecom_aibot_encoding_aes_key,
            receive_id=settings.wecom_aibot_bot_id,
            intent_router=intent_router,
            agent_registry=agent_registry,
            db_session_factory=async_session,
        )
    )
    logger.info("AIBot callback route: registered")
