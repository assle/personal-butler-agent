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

支持群聊总结测试:
  发送 chat_type="group" + chat_id → 保存消息到 DB，触发关键词时走 summarize_group
"""
import time
import logging
from fastapi import APIRouter, Depends
from openai import APIError
from sqlalchemy.ext.asyncio import AsyncSession
from src.schemas.request import DebugMessageRequest
from src.schemas.response import DebugMessageResponse
from src.db.session import get_db
from src.intent.router import IntentRouter
from src.agents.registry import AgentRegistry

logger = logging.getLogger(__name__)

_SUMMARIZE_KEYWORDS = ["总结", "摘要", "概括", "汇总"]


def _is_trigger(content: str) -> bool:
    """检测消息是否触发群聊总结（内容中包含总结类关键词）

    参数:
        content: 消息文本内容

    返回:
        bool: 命中关键词返回 True
    """
    return any(kw in content for kw in _SUMMARIZE_KEYWORDS)


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
            req: 调试消息请求体（user_id, message, chat_type, chat_id）
            db: 数据库异步会话，通过 FastAPI 依赖注入

        返回:
            DebugMessageResponse: 包含意图、置信度、回复文本和可选数据的响应
        """
        # 群聊消息：保存到数据库用于后续总结
        if req.chat_type == "group" and req.chat_id:
            from src.models.group_message import GroupMessage
            await GroupMessage.save(
                db, req.chat_id, req.user_id, req.message,
                int(time.time()),
            )
            logger.info("Debug: saved group message, chat_id=%s, user=%s",
                        req.chat_id, req.user_id)

            # 非触发消息：静默收集，不回复
            if not _is_trigger(req.message):
                logger.info("Debug: non-trigger group message, returning silently")
                return DebugMessageResponse(
                    intent="collect_group",
                    confidence=1.0,
                    response="",
                    data={"chat_id": req.chat_id, "saved": True},
                )

            # 触发消息：使用 summarize_group 意图
            agent = agent_registry.get("summarize_group")
            if agent is None:
                return DebugMessageResponse(
                    intent="summarize_group",
                    confidence=1.0,
                    response="抱歉，无法处理该消息",
                )
            try:
                result = await agent.handle(
                    "summarize_group", req.message, req.user_id, db,
                    extra_state={"chat_id": req.chat_id, "chat_type": "group"},
                )
                return DebugMessageResponse(
                    intent="summarize_group",
                    confidence=1.0,
                    response=result.reply,
                    data=result.data,
                )
            except APIError as e:
                return DebugMessageResponse(
                    intent="summarize_group",
                    confidence=1.0,
                    response="LLM 服务暂时不可用，请稍后重试。",
                    data={"error": str(e)},
                )

        # 私聊：走意图路由
        intent, confidence = await intent_router.route(req.message)
        agent = agent_registry.get(intent)
        if agent is None:
            return DebugMessageResponse(
                intent=intent,
                confidence=confidence,
                response="抱歉，无法处理该消息",
            )
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
