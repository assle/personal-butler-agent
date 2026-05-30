"""
Personal Butler Agent 应用入口
负责 FastAPI 应用初始化、单例组件创建和路由注册

Workflow:
1. 创建 LLMClient、IntentRouter、各业务 agent 单例
2. 向 AgentRegistry 注册所有 intent → agent 映射
3. lifespan 中初始化数据库表结构
4. 注册调试路由（始终可用）
5. 条件注册企业微信回调路由（仅当 WECHAT_CORP_ID 和 WECHAT_TOKEN 已配置）
6. 条件创建企业微信群推送客户端（仅当 WECHAT_WEBHOOK_URL 已配置）
"""
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
agent_registry.register("make_meal_plan", meal_agent)
agent_registry.register("qa", qa_agent)
agent_registry.register("unknown", qa_agent)
agent_registry.set_fallback(qa_agent)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.db.base import Base
    from src.db.session import engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Personal Butler Agent", version="0.1.0", lifespan=lifespan)

# 调试路由（始终注册，用于本地开发测试）
debug_router = create_debug_router(
    intent_router=intent_router,
    agent_registry=agent_registry,
)
app.include_router(debug_router)

# 企业微信回调路由（仅当配置了 CorpID 和 Token 时注册）
if settings.wechat_corp_id and settings.wechat_token:
    from src.wechat.router import create_wechat_router

    wechat_router = create_wechat_router(
        intent_router=intent_router,
        agent_registry=agent_registry,
        corp_id=settings.wechat_corp_id,
        token=settings.wechat_token,
        encoding_aes_key=settings.wechat_encoding_aes_key,
    )
    app.include_router(wechat_router)

# 企业微信群推送客户端（仅当配置了 Webhook URL 时创建）
_webhook_client = None
if settings.wechat_webhook_url:
    from src.wechat.webhook import WechatWebhookClient

    _webhook_client = WechatWebhookClient(settings.wechat_webhook_url)
