from fastapi import APIRouter, Depends
from openai import APIError
from sqlalchemy.ext.asyncio import AsyncSession
from src.schemas.request import DebugMessageRequest
from src.schemas.response import DebugMessageResponse
from src.db.session import get_db
from src.intent.router import IntentRouter
from src.agents.registry import AgentRegistry


def create_debug_router(
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
) -> APIRouter:
    router = APIRouter(prefix="/api/debug", tags=["debug"])

    @router.post("/message")
    async def debug_message(
        req: DebugMessageRequest, db: AsyncSession = Depends(get_db)
    ) -> DebugMessageResponse:
        intent, confidence = await intent_router.route(req.message)

        agent = agent_registry.get(intent)
        try:
            result = await agent.handle(intent, req.message, req.user_id, db)
        except APIError as e:
            return DebugMessageResponse(
                intent=intent,
                confidence=confidence,
                response="LLM 服务暂时不可用，请稍后重试。",
                data={"error": str(e)},
            )

        return DebugMessageResponse(
            intent=intent,
            confidence=confidence,
            response=result.reply,
            data=result.data,
        )

    return router
