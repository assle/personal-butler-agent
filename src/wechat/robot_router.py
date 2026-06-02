"""
企业微信智能机器人 API 模式回调路由（URL 验证 + 消息接收）
提供 create_robot_router 工厂函数，返回挂载了 GET/POST /api/wechat/robot/callback 的 APIRouter

与自建应用回调的关键区别:
  1. 使用独立的 WECHAT_ROBOT_TOKEN / WECHAT_ROBOT_ENCODING_AES_KEY 配置
  2. 加解密时 receiveid 为空字符串（自建应用使用 CorpID）
  3. 消息格式为智能机器人专用 JSON（非自建应用 XML）
  4. 回复通过 response_url 主动 POST JSON（非被动加密 XML 回复）

Workflow:
GET /api/wechat/robot/callback - URL 验证:
  1. 从 query params 提取 msg_signature, timestamp, nonce, echostr
  2. verify_signature 验签 → 失败返回 403
  3. decrypt echostr（receiveid=""）→ 返回解密后的明文

POST /api/wechat/robot/callback - 消息接收:
  1. 从 JSON body 提取 encrypt 字段，验签 + 解密（receiveid=""）
  2. 解析智能机器人 JSON 结构: from.userid, text.content, chatid, chattype, response_url
  3. 群聊消息保存到 DB，触发词检测 → summarize_group（POST 到 response_url）
  4. 非触发群聊消息静默收集，返回 success
  5. 私聊消息 intent 路由 → agent 处理 → POST 到 response_url
  6. 始终返回 200 success（不被动回复），所有内容通过 response_url 推送
"""
import asyncio
import json
import logging
import time

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response
from openai import APIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.registry import AgentRegistry
from src.db.session import get_db
from src.intent.router import IntentRouter

from .crypto import (
    CorpIDMismatch,
    DecryptError,
    decrypt,
    verify_signature,
)

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _h = logging.StreamHandler()
    _h.setLevel(logging.INFO)
    logger.addHandler(_h)


def create_robot_router(
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    token: str,
    encoding_aes_key: str,
) -> APIRouter:
    """创建企业微信智能机器人回调路由

    智能机器人与自建应用的关键区别:
      - receiveid 为空字符串 ""
      - 消息内容为智能机器人专用 JSON 格式
      - 回复通过 response_url 主动推送（非被动加密 XML）

    参数:
        intent_router: 意图路由器
        agent_registry: agent 注册表
        token: 智能机器人回调配置 Token
        encoding_aes_key: 智能机器人回调配置 EncodingAESKey

    返回:
        APIRouter: 挂载了 GET/POST /api/wechat/robot/callback 的路由
    """
    router = APIRouter(prefix="/api/wechat/robot", tags=["wechat-robot"])

    @router.get("/callback")
    async def verify_url(
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
        echostr: str = Query(...),
    ):
        """智能机器人回调 URL 验证（GET 请求）

        与自建应用的区别: echostr 解密时 receiveid 为空字符串

        参数:
            msg_signature: 企业微信发送的消息签名
            timestamp: 时间戳
            nonce: 随机数
            echostr: 加密的验证字符串

        返回:
            PlainTextResponse: 解密后的 echostr 明文，或 403 签名错误
        """
        if not verify_signature(token, timestamp, nonce, echostr, msg_signature):
            logger.warning("Robot URL verification: signature mismatch")
            return Response(status_code=403, content="signature error")

        try:
            plain = decrypt(encoding_aes_key, echostr, "")
            return Response(content=plain, media_type="text/plain")
        except (DecryptError, CorpIDMismatch) as e:
            logger.error("Robot URL verification: decrypt failed: %s", e)
            return Response(status_code=403, content="decrypt error")

    @router.post("/callback")
    async def receive_message(
        request: Request,
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
        db: AsyncSession = Depends(get_db),
    ):
        """接收智能机器人回调消息（POST 请求）

        消息格式为智能机器人专用 JSON（非自建应用 XML）。
        所有回复通过 response_url 主动推送，不通过回调响应返回。

        参数:
            request: FastAPI Request 对象
            msg_signature: 消息签名
            timestamp: 时间戳
            nonce: 随机数
            db: 数据库异步会话，通过 FastAPI 依赖注入

        返回:
            Response: 始终返回 200 success，实际回复通过 response_url 推送
        """
        # 解析外层 JSON body，提取 encrypt 字段
        try:
            body = await request.json()
        except Exception:
            logger.warning("Robot callback: failed to parse JSON body")
            return Response(content="success")
        encrypt_content = body.get("encrypt", "")

        # 验签
        if not verify_signature(token, timestamp, nonce, encrypt_content, msg_signature):
            logger.warning("Robot callback: signature mismatch")
            return Response(status_code=403, content="signature error")

        # 解密（智能机器人 receiveid 为空字符串）
        try:
            decrypted = decrypt(encoding_aes_key, encrypt_content, "")
        except (DecryptError, CorpIDMismatch) as e:
            logger.error("Robot callback: decrypt failed: %s", e)
            return Response(content="success")

        logger.info("Robot callback: decrypted inner message: %s", decrypted[:500])

        # 解析智能机器人专用 JSON 格式
        try:
            inner = json.loads(decrypted)
        except json.JSONDecodeError:
            logger.error("Robot callback: inner message parse failed")
            return Response(content="success")

        # 智能机器人 JSON 字段:
        #   from.userid  - 发送者 userid
        #   text.content - 消息文本内容
        #   chatid       - 群聊 ID（私聊时可能不存在）
        #   chattype     - "group" 或 "single"
        #   msgtype      - 消息类型（text/image/...）
        #   response_url - 用于主动回复的临时 URL
        #   aibotid      - 智能机器人 ID
        #   msgid        - 消息 ID
        from_user = inner.get("from", {}).get("userid", "")
        msg_type = inner.get("msgtype", "text")
        # 根据消息类型提取文本内容
        if msg_type == "voice":
            content = inner.get("voice", {}).get("content", "")
            if not content:
                logger.info("Robot callback: voice recognition empty, silently ignoring")
                return Response(content="success")
            logger.info("Robot callback: voice recognition: %s", content[:200])
        else:
            content = inner.get("text", {}).get("content", "")
        chat_id = inner.get("chatid", "")
        chat_type = inner.get("chattype", "single")
        response_url = inner.get("response_url", "")

        logger.info(
            "Robot callback: parsed msg_type=%s, from_user=%s, chat_type=%s, chat_id=%s, content=%s",
            msg_type, from_user, chat_type, chat_id, content[:200],
        )

        # 群聊消息：始终保存到数据库用于后续总结
        is_group_trigger = False
        if chat_type == "group" and chat_id:
            from src.models.group_message import GroupMessage
            await GroupMessage.save(db, chat_id, from_user, content, int(time.time()))
            await GroupMessage.cleanup(db, chat_id, keep=200)
            logger.info("Robot callback: saved group message, chat_id=%s", chat_id)

            if not _is_summarize_trigger(content):
                logger.info("Robot callback: non-trigger group message, no reply")
                return Response(content="success")
            is_group_trigger = True

        # 非文本消息
        # 非文本且非语音消息
        if msg_type not in ("text", "voice"):
            reply_text = "暂不支持该消息类型"
        elif is_group_trigger:
            # 群聊触发消息：使用 summarize_group 代理
            agent = agent_registry.get("summarize_group")
            if agent is None:
                reply_text = "抱歉，无法处理该消息"
            else:
                try:
                    result = await agent.handle(
                        "summarize_group", content, from_user, db,
                        extra_state={"chat_id": chat_id, "chat_type": "group"},
                    )
                    reply_text = result.reply
                except APIError as e:
                    logger.error("Robot callback: APIError from group agent: %s", e)
                    reply_text = "LLM 服务暂时不可用，请稍后重试。"
        else:
            # 私聊消息：意图路由 + agent 处理
            try:
                intent, _confidence = await intent_router.route(content)
                logger.info("Robot callback: intent=%s, confidence=%s", intent, _confidence)
                agent = agent_registry.get(intent)

                if agent is None:
                    reply_text = "抱歉，无法处理该消息"
                else:
                    try:
                        result = await agent.handle(
                            intent,
                            content,
                            from_user,
                            db,
                            extra_state={"chat_type": chat_type, "chat_id": chat_id or None},
                        )
                        reply_text = result.reply
                    except APIError as e:
                        logger.error("Robot callback: APIError from agent: %s", e)
                        reply_text = "LLM 服务暂时不可用，请稍后重试。"
            except Exception as e:
                logger.exception("Robot callback: unexpected error in agent pipeline: %s", e)
                reply_text = "抱歉，处理消息时遇到错误，请稍后重试。"

        logger.info("Robot callback: reply_text=%s", reply_text[:200])

        # 通过 response_url 主动推送回复（JSON 格式）
        if response_url:
            await _post_reply(response_url, reply_text)
        else:
            logger.warning("Robot callback: no response_url, reply dropped: %s", reply_text[:100])

        return Response(content="success")

    return router


async def _post_reply(response_url: str, content: str) -> None:
    """向 response_url 发送 JSON 格式的主动回复

    智能机器人 response_url 仅支持两种 msgtype:
      - markdown: {"msgtype": "markdown", "markdown": {"content": "回复内容"}}
      - template_card: 模板卡片消息
      text 类型不被智能机器人 response_url 支持

    参数:
        response_url: 企业微信智能机器人提供的临时回复 URL
        content: 回复文本内容（支持 Markdown 格式）
    """
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(response_url, json=payload)
            logger.info(
                "Robot reply posted: status=%s, body=%s",
                resp.status_code, resp.text[:200],
            )
    except Exception as e:
        logger.error("Robot reply: failed to post to response_url: %s", e)


def _is_summarize_trigger(content: str) -> bool:
    """检测消息是否触发群聊总结（内容中包含总结类关键词）

    参数:
        content: 消息文本内容

    返回:
        bool: 命中关键词返回 True
    """
    keywords = ["总结", "摘要", "概括", "汇总"]
    return any(kw in content for kw in keywords)
