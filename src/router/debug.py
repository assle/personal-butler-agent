"""
调试路由
提供 POST /api/debug/message 端点，模拟企业微信消息回调用于本地开发测试

在总流程中的位置:
  用户请求 → POST /api/debug/message → 解析请求体 → IntentRouter.route()
  → AgentRegistry.get(intent) → agent.handle() → DebugMessageResponse

与 wechat 路由的区别:
  - 无需加密/解密
  - 返回 JSON 而非 XML
  - 始终注册，不依赖企业微信配置
"""
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
    """创建调试路由

    参数:
        intent_router: 意图路由器实例
        agent_registry: Agent 注册表实例

    返回:
        APIRouter: 挂载了 POST /api/debug/message 的路由
    """
    router = APIRouter(prefix="/api/debug", tags=["debug"])

    @router.post("/message")
    async def debug_message(
        req: DebugMessageRequest, db: AsyncSession = Depends(get_db)
    ) -> DebugMessageResponse:
        """处理调试消息，走完整的意图路由 → agent 处理链路

        参数:
            req: 调试消息请求体（user_id, message, timestamp）
            db: 数据库异步会话，通过 FastAPI 依赖注入

        返回:
            DebugMessageResponse: 包含意图、置信度、回复文本和可选数据的响应
        """
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
