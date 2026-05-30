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

debug_router = create_debug_router(
    intent_router=intent_router,
    agent_registry=agent_registry,
)
app.include_router(debug_router)
