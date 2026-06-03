"""
企业微信长连接消息处理回调
从 WebSocket 收到消息后，将可回复消息交给 ButlerAgent 处理并回复

Workflow:
  ws 收到 aibot_msg_callback → handle_ws_message()
    → 解析消息字段
    → 群聊消息保存到 DB + 触发词检测
    → 文本/语音消息交给 ButlerAgent 处理
    → ws_client.send_reply() 回复
"""
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.butler import ButlerAgent
from src.agents.registry import AgentRegistry
from src.intent.router import IntentRouter

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)

_SUMMARIZE_KEYWORDS = ["总结", "摘要", "概括", "汇总"]


async def handle_ws_message(
    msg: dict,
    req_id: str,
    ws_client,
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    butler_agent: ButlerAgent | AsyncSession,
    db: AsyncSession | None = None,
):
    """处理从 WebSocket 收到的消息回调

    参数:
        msg: aibot_msg_callback 的 body 部分，包含 from.userid, text.content, chatid 等
        req_id: 原始消息回调 headers 中的 req_id，回复时需要透传
        ws_client: WeComWSClient 实例，用于回复消息
        intent_router: 兼容保留的意图路由器，可回复消息不再直接使用
        agent_registry: 兼容保留的 agent 注册表，可回复消息不再直接使用
        butler_agent: 小管家总控 agent，用于处理可回复文本和语音消息
        db: 数据库异步会话
    """
    if db is None:
        db = butler_agent
        butler_agent = None

    from_user = msg.get("from", {}).get("userid", "")
    msg_type = msg.get("msgtype", "text")

    # 提取文本内容
    if msg_type == "voice":
        content = msg.get("voice", {}).get("content", "")
        if not content:
            logger.info("WS: voice recognition empty, ignoring")
            return
    else:
        content = msg.get("text", {}).get("content", "")

    chat_id = msg.get("chatid", "")
    chat_type = msg.get("chattype", "single")

    logger.info(
        "WS handler: msg_type=%s, from_user=%s, chat_type=%s, chat_id=%s, content=%s",
        msg_type, from_user, chat_type, chat_id, content[:200],
    )

    # 构建 extra_state（会话上下文）
    extra_state: dict = {"chat_type": chat_type, "chat_id": chat_id or None}

    # 群聊消息处理
    is_group_trigger = False
    if chat_type == "group" and chat_id:
        from src.models.group_message import GroupMessage
        await GroupMessage.save(db, chat_id, from_user, content, int(time.time()))
        await GroupMessage.cleanup(db, chat_id, keep=200)

        if _is_summarize_trigger(content):
            is_group_trigger = True
        else:
            logger.info("WS handler: non-trigger group message, no reply")
            return

    # 非文本且非语音消息
    if msg_type not in ("text", "voice"):
        reply_text = "暂不支持该消息类型"
    elif butler_agent is None and is_group_trigger:
        agent = agent_registry.get("summarize_group")
        if agent is None:
            reply_text = "抱歉，无法处理该消息"
        else:
            try:
                result = await agent.handle(
                    "summarize_group", content, from_user, db,
                    extra_state=extra_state,
                )
                reply_text = result.reply
            except Exception as e:
                logger.exception("WS handler: agent error: %s", e)
                reply_text = "抱歉，处理消息时遇到错误"
    elif butler_agent is None:
        # 兼容旧调用方：未注入 ButlerAgent 时继续走原有意图路由
        try:
            intent, _confidence = await intent_router.route(content)
            logger.info("WS handler: intent=%s", intent)
            agent = agent_registry.get(intent)
            if agent is None:
                reply_text = "抱歉，无法处理该消息"
            else:
                try:
                    result = await agent.handle(
                        intent, content, from_user, db,
                        extra_state=extra_state,
                    )
                    reply_text = result.reply
                except Exception as e:
                    logger.exception("WS handler: agent error: %s", e)
                    reply_text = "LLM 服务暂时不可用，请稍后重试。"
        except Exception as e:
            logger.exception("WS handler: unexpected error: %s", e)
            reply_text = "抱歉，处理消息时遇到错误"
    else:
        # 可回复消息统一交给 ButlerAgent 处理
        try:
            if is_group_trigger:
                logger.info("WS handler: group trigger routed to butler")
            result = await butler_agent.handle(
                "butler", content, from_user, db,
                extra_state=extra_state,
            )
            reply_text = result.reply
        except Exception as e:
            logger.exception("WS handler: butler agent error: %s", e)
            reply_text = "LLM 服务暂时不可用，请稍后重试。"

    logger.info("WS handler: reply_text=%s", reply_text[:200])
    await ws_client.send_reply(req_id, reply_text)


def _is_summarize_trigger(content: str) -> bool:
    """检测消息是否触发群聊总结"""
    return any(kw in content for kw in _SUMMARIZE_KEYWORDS)
