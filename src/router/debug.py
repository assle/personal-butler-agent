from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.schemas.request import DebugMessageRequest
from src.schemas.response import DebugMessageResponse
from src.db.session import get_db
from src.intent.router import IntentRouter
from src.agents.fitness import FitnessAgent
from src.agents.summary import SummaryAgent
from src.agents.meal import MealAgent
from src.agents.qa import QAAgent


def create_debug_router(
    intent_router: IntentRouter,
    fitness_agent: FitnessAgent,
    summary_agent: SummaryAgent,
    meal_agent: MealAgent,
    qa_agent: QAAgent,
) -> APIRouter:
    router = APIRouter(prefix="/api/debug", tags=["debug"])

    @router.post("/message")
    async def debug_message(
        req: DebugMessageRequest, db: AsyncSession = Depends(get_db)
    ) -> DebugMessageResponse:
        intent, confidence = await intent_router.route(req.message)

        agent_map = {
            "log_training": fitness_agent,
            "today_plan": fitness_agent,
            "summarize_text": summary_agent,
            "make_meal_plan": meal_agent,
            "qa": qa_agent,
            "unknown": qa_agent,
        }

        agent = agent_map.get(intent, qa_agent)
        result = await agent.handle(intent, req.message, req.user_id, db)

        return DebugMessageResponse(
            intent=intent,
            confidence=confidence,
            response=result.reply,
            data=result.data,
        )

    return router
