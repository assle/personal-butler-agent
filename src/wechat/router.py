"""
企业微信回调路由（URL 验证 + 消息接收）
提供 create_wechat_router 工厂函数，返回挂载了 GET/POST /api/wechat/callback 的 APIRouter

Workflow:
GET /api/wechat/callback - URL 验证:
  1. 从 query params 提取 msg_signature, timestamp, nonce, echostr
  2. verify_signature 验签 → 失败返回 403
  3. decrypt echostr → 返回解密后的明文

POST /api/wechat/callback - 消息接收:
  1. 从 body 解析 EncryptedMessage，从 query params 获取签名参数
  2. verify_signature 验签 → 失败返回 403
  3. decrypt → 解析内层消息（JSON 格式）→ 提取 user_id 和 message
  4. intent_router.route(message) → agent_registry.get(intent) → agent.handle()
  5. 构建回复 XML → encrypt → 返回加密的 XML 响应
"""
import json
import logging
import time

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
    encrypt,
    verify_signature,
)
from .messages import build_encrypted_reply_xml, build_reply_xml

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _h = logging.StreamHandler()
    _h.setLevel(logging.INFO)
    logger.addHandler(_h)


def create_wechat_router(
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    corp_id: str,
    token: str,
    encoding_aes_key: str,
) -> APIRouter:
    """创建企业微信回调路由

    参数:
        intent_router: 意图路由器
        agent_registry: agent 注册表
        corp_id: 企业微信 CorpID
        token: 回调配置 Token
        encoding_aes_key: 回调配置 EncodingAESKey

    返回:
        APIRouter: 挂载了 GET/POST /api/wechat/callback 的路由
    """
    router = APIRouter(prefix="/api/wechat", tags=["wechat"])

    @router.get("/callback")
    async def verify_url(
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
        echostr: str = Query(...),
    ):
        """企业微信回调 URL 验证（GET 请求）

        参数:
            msg_signature: 企业微信发送的消息签名
            timestamp: 时间戳
            nonce: 随机数
            echostr: 加密的验证字符串

        返回:
            PlainTextResponse: 解密后的 echostr 明文，或 403 签名错误
        """
        if not verify_signature(token, timestamp, nonce, echostr, msg_signature):
            logger.warning("WeChat URL verification: signature mismatch")
            return Response(status_code=403, content="signature error")

        try:
            plain = decrypt(encoding_aes_key, echostr, corp_id)
            return Response(content=plain, media_type="text/plain")
        except (DecryptError, CorpIDMismatch) as e:
            logger.error("WeChat URL verification: decrypt failed: %s", e)
            return Response(status_code=403, content="decrypt error")

    @router.post("/callback")
    async def receive_message(
        request: Request,
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
        db: AsyncSession = Depends(get_db),
    ):
        """接收企业微信用户消息（POST 请求）

        参数:
            request: FastAPI Request 对象，支持 JSON 和 XML body 格式
            msg_signature: 消息签名
            timestamp: 时间戳
            nonce: 随机数
            db: 数据库异步会话，通过 FastAPI 依赖注入

        返回:
            Response: 加密的 XML 回复，或错误响应
        """
        # 解析外层请求体（支持 JSON 和 XML 两种格式）
        content_type = request.headers.get("content-type", "")
        logger.info("WeChat callback: POST received, content-type=%s", content_type)
        if "xml" in content_type:
            raw_body = await request.body()
            from .messages import parse_encrypted_xml
            parsed = parse_encrypted_xml(raw_body)
            encrypt_content = parsed.encrypt
        else:
            try:
                body = await request.json()
            except Exception:
                return Response(content="success")
            encrypt_content = body.get("encrypt", "")

        # 验签
        if not verify_signature(token, timestamp, nonce, encrypt_content, msg_signature):
            logger.warning("WeChat callback: signature mismatch")
            return Response(status_code=403, content="signature error")

        # 解密
        try:
            decrypted = decrypt(encoding_aes_key, encrypt_content, corp_id)
        except (DecryptError, CorpIDMismatch) as e:
            logger.error("WeChat callback: decrypt failed: %s", e)
            return Response(content="success")

        logger.info("WeChat callback: decrypted inner message: %s", decrypted[:500])

        # 解析内层消息：先尝试企业微信原生 XML 格式，回退 JSON 格式（测试用）
        try:
            from .messages import parse_inner_xml
            inner = parse_inner_xml(decrypted)
            to_user = inner.to_user_name
            from_user = inner.from_user_name
            msg_type = inner.msg_type
            content = inner.content
            chat_id = inner.chat_id
            chat_type = inner.chat_type
            inner_create_time = inner.create_time
        except Exception as e:
            logger.info("WeChat callback: XML parse failed (%s), trying JSON fallback", e)
            try:
                inner = json.loads(decrypted)
                to_user = inner.get("to_user_name", corp_id)
                from_user = inner.get("from_user_name", "")
                msg_type = inner.get("msg_type", "text")
                content = inner.get("content", "")
                chat_id = inner.get("chat_id", "")
                chat_type = inner.get("chat_type", "single")
                inner_create_time = inner.get("create_time", 0)
            except json.JSONDecodeError:
                logger.error("WeChat callback: inner message parse failed (both XML and JSON)")
                return Response(content="success")

        # 语音消息：从 Recognition 字段提取识别文本，空则静默忽略
        if msg_type == "voice":
            voice_text = (
                inner.recognition
                if not isinstance(inner, dict)
                else inner.get("recognition", "")
            )
            if not voice_text:
                logger.info("WeChat callback: voice recognition empty, silently ignoring")
                return Response(content="success")
            content = voice_text
            msg_type = "text"
            logger.info("WeChat callback: voice recognition: %s", content[:200])

        logger.info("WeChat callback: parsed msg_type=%s, from_user=%s, to_user=%s, chat_type=%s, content=%s",
                    msg_type, from_user, to_user, chat_type, content[:200])

        # 群聊消息：始终保存到数据库用于后续总结
        is_group_trigger = False
        if chat_type == "group" and chat_id:
            from src.models.group_message import GroupMessage
            await GroupMessage.save(db, chat_id, from_user, content, inner_create_time)
            await GroupMessage.cleanup(db, chat_id, keep=200)
            logger.info("WeChat callback: saved group message, chat_id=%s", chat_id)

            # 非触发消息：静默收集，不回复到群聊
            if not _is_summarize_trigger(content):
                logger.info("WeChat callback: non-trigger group message, returning silently")
                return Response(content="success")
            is_group_trigger = True

        # 非文本消息：回复不支持
        intent = "non_text"
        if msg_type != "text":
            logger.info("WeChat callback: non-text message type=%s, replying with unsupported", msg_type)
            reply_text = "暂不支持该消息类型"
        elif is_group_trigger:
            # 群聊触发消息：使用 summarize_group 意图，传入 chat_id 和 chat_type
            intent = "summarize_group"
            agent = agent_registry.get(intent)
            if agent is None:
                reply_text = "抱歉，无法处理该消息"
            else:
                try:
                    result = await agent.handle(
                        intent, content, from_user, db,
                        extra_state={"chat_id": chat_id, "chat_type": "group"},
                    )
                    reply_text = result.reply
                except APIError as e:
                    logger.error("WeChat callback: APIError from group agent: %s", e)
                    reply_text = "LLM 服务暂时不可用，请稍后重试。"
        else:
            # 意图路由 + agent 处理（私聊）
            try:
                intent, _confidence = await intent_router.route(content)
                logger.info("WeChat callback: intent=%s, confidence=%s", intent, _confidence)
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
                        logger.error("WeChat callback: APIError from agent: %s", e)
                        reply_text = "LLM 服务暂时不可用，请稍后重试。"
            except Exception as e:
                logger.exception("WeChat callback: unexpected error in agent pipeline: %s", e)
                reply_text = "抱歉，处理消息时遇到错误，请稍后重试。"

        logger.info("WeChat callback: intent=%s, reply_text=%s", intent, reply_text[:200])

        # 构建企业微信要求的明文回复 XML 后再加密
        reply_plain_xml = build_reply_xml(
            to_user=from_user,
            from_user=to_user or corp_id,
            content=reply_text,
        )
        logger.info("WeChat callback: reply plain XML (inner): %s", reply_plain_xml)
        reply_encrypted = encrypt(encoding_aes_key, reply_plain_xml, corp_id)
        now_ts = str(int(time.time()))
        reply_sig = _compute_signature(token, now_ts, nonce, reply_encrypted)

        xml = build_encrypted_reply_xml(reply_encrypted, reply_sig, now_ts, nonce)
        logger.info("WeChat callback: final reply XML (outer): %s", xml)
        return Response(content=xml, media_type="application/xml")

    return router


def _compute_signature(token: str, timestamp: str, nonce: str, encrypt_msg: str) -> str:
    """计算消息签名（SHA1 排序拼接）

    参数:
        token: 企业微信 Token
        timestamp: 时间戳
        nonce: 随机数
        encrypt_msg: 加密后的消息

    返回:
        str: 十六进制 SHA1 签名
    """
    import hashlib
    parts = sorted([token, timestamp, nonce, encrypt_msg])
    return hashlib.sha1("".join(parts).encode()).hexdigest()


def _is_summarize_trigger(content: str) -> bool:
    """检测消息是否触发群聊总结（内容中包含总结类关键词）

    参数:
        content: 消息文本内容

    返回:
        bool: 命中关键词返回 True
    """
    keywords = ["总结", "摘要", "概括", "汇总"]
    return any(kw in content for kw in keywords)
