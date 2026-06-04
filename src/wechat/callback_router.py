"""
智能机器人 URL 回调 FastAPI 路由
提供 GET URL 验证和 POST 消息回调入口，入站消息先落库再后台处理

Workflow:
1. GET /api/wechat/aibot/callback 解密 echostr，完成企业微信 URL 验证
2. POST 接收加密 JSON/XML 或明文 JSON 回调
3. 按 msgid 写入 inbound_messages，重复回调直接返回成功
4. 新消息通过 BackgroundTasks 调用场景分发层，并用 response_url 回复
"""
from __future__ import annotations

import inspect
import json
import logging
import xml.etree.ElementTree as ET
from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.wechat.callback_crypto import WeComCallbackCrypto
from src.wechat.callback_handler import ResponseUrlReplyClient, handle_callback_message
from src.wechat.callback_inbox import (
    mark_failed,
    mark_processed,
    mark_processing,
    record_inbound_message,
)

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)


DbSessionFactory = Callable[[], AsyncSession]


def create_aibot_callback_router(
    token: str,
    encoding_aes_key: str,
    receive_id: str,
    private_agent,
    group_agent,
    db_session_factory,
    reply_client: ResponseUrlReplyClient | None = None,
) -> APIRouter:
    """创建智能机器人 URL 回调路由

    参数:
        token: 智能机器人 URL 回调 Token
        encoding_aes_key: 智能机器人 URL 回调 EncodingAESKey
        receive_id: 智能机器人 BotID，用于校验消息体 aibotid
        private_agent: 私聊场景 agent
        group_agent: 群聊 @ 场景 agent
        db_session_factory: 异步数据库会话工厂
        reply_client: 可选 response_url 回复客户端

    返回:
        APIRouter: 可挂载到 FastAPI app 的路由
    """
    router = APIRouter(prefix="/api/wechat/aibot", tags=["wechat-aibot"])
    crypto = WeComCallbackCrypto(token, encoding_aes_key)
    reply_client = reply_client or ResponseUrlReplyClient()

    @router.get("/callback")
    async def verify_callback(
        msg_signature: str,
        timestamp: str,
        nonce: str,
        echostr: str,
    ):
        """处理企业微信 URL 验证请求

        参数:
            msg_signature: 企业微信签名
            timestamp: 时间戳
            nonce: 随机串
            echostr: 加密回显字符串

        返回:
            PlainTextResponse: 解密后的 echostr 明文
        """
        try:
            plain = crypto.decrypt_if_signature_valid(msg_signature, timestamp, nonce, echostr)
        except ValueError as e:
            logger.warning("AIBot callback verify failed: %s", e)
            raise HTTPException(status_code=403, detail="invalid signature") from e
        return PlainTextResponse(plain)

    @router.post("/callback")
    async def receive_callback(
        request: Request,
        background_tasks: BackgroundTasks,
        msg_signature: str = "",
        timestamp: str = "",
        nonce: str = "",
    ):
        """处理企业微信智能机器人消息回调

        参数:
            request: FastAPI 请求对象
            background_tasks: FastAPI 后台任务容器
            msg_signature: 企业微信签名，密文回调时必需
            timestamp: 时间戳，密文回调时必需
            nonce: 随机串，密文回调时必需

        返回:
            dict: 企微可识别的成功响应
        """
        try:
            frame = await _parse_callback_request(request, crypto, msg_signature, timestamp, nonce)
            msg = _extract_message_body(frame, receive_id)
        except ValueError as e:
            logger.warning("AIBot callback parse failed: %s", e)
            raise HTTPException(status_code=400, detail=str(e)) from e

        async with _session_scope(db_session_factory) as db:
            result = await record_inbound_message(db, msg)
            await db.commit()

        if result.should_process:
            background_tasks.add_task(
                process_recorded_message,
                msg,
                reply_client,
                private_agent,
                group_agent,
                db_session_factory,
            )
        '''
        如果这条消息需要处理：
        不在当前请求里立刻处理
        而是把 process_recorded_message 加入后台任务队列
        当前接口可以先返回响应
        响应返回后，FastAPI 再执行这个后台任务
        这是因为企业微信回调要求服务器尽快返回*响应*
        '''
        return {"errcode": 0, "errmsg": "ok"}

    return router


async def process_recorded_message(
    msg: dict,
    reply_client: ResponseUrlReplyClient,
    private_agent,
    group_agent,
    db_session_factory,
):
    """后台处理已落库的智能机器人回调消息

    参数:
        msg: 智能机器人消息体
        reply_client: response_url 回复客户端
        private_agent: 私聊场景 agent
        group_agent: 群聊 @ 场景 agent
        db_session_factory: 异步数据库会话工厂
    """
    msgid = msg.get("msgid", "")
    async with _session_scope(db_session_factory) as db:
        try:
            await mark_processing(db, msgid)
            await handle_callback_message(
                msg,
                reply_client,
                private_agent,
                group_agent,
                db,
            )
            await mark_processed(db, msgid)
            await db.commit()
        except Exception as e:
            await db.rollback()
            async with _session_scope(db_session_factory) as failed_db:
                await mark_failed(failed_db, msgid, str(e))
                await failed_db.commit()
            logger.exception("AIBot callback: failed to process msgid=%s", msgid)


async def _parse_callback_request(
    request: Request,
    crypto: WeComCallbackCrypto,
    msg_signature: str,
    timestamp: str,
    nonce: str,
) -> dict:
    """解析回调请求，支持密文 JSON/XML 和明文 JSON

    参数:
        request: FastAPI 请求对象
        crypto: 回调加解密器
        msg_signature: 企业微信签名
        timestamp: 时间戳
        nonce: 随机串

    返回:
        dict: 智能机器人回调帧或消息体
    """
    body = await request.body()
    if not body:
        raise ValueError("empty callback body")
    parsed = _load_json_or_xml(body)
    encrypt_text = _extract_encrypt_text(parsed)
    if encrypt_text:
        plain = crypto.decrypt_if_signature_valid(msg_signature, timestamp, nonce, encrypt_text)
        return json.loads(plain)
    if isinstance(parsed, dict):
        return parsed
    raise ValueError("unsupported callback body")


def _load_json_or_xml(body: bytes) -> dict:
    """将请求体解析为 JSON dict 或 XML dict

    参数:
        body: HTTP 请求体字节

    返回:
        dict: 解析后的结构
    """
    text = body.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    root = ET.fromstring(text)
    return {child.tag: child.text or "" for child in root}


def _extract_encrypt_text(parsed: dict) -> str:
    """从 JSON/XML 结构中提取 Encrypt/encrypt 字段

    参数:
        parsed: 已解析的回调请求体

    返回:
        str: 密文；未找到返回空字符串
    """
    return parsed.get("encrypt") or parsed.get("Encrypt") or ""


def _extract_message_body(frame: dict, expected_aibotid: str = "") -> dict:
    """从智能机器人回调帧中提取消息体

    参数:
        frame: 回调帧，可能是智能机器人包装帧或直接消息体
        expected_aibotid: 可选智能机器人 BotID，用于校验消息体归属

    返回:
        dict: 智能机器人消息体
    """
    if frame.get("cmd") == "aibot_event_callback":
        raise ValueError("event callback is not supported yet")
    if frame.get("cmd") == "aibot_msg_callback":
        body = frame.get("body")
        if not isinstance(body, dict):
            raise ValueError("aibot_msg_callback missing body")
        _validate_aibotid(body, expected_aibotid)
        return body
    if frame.get("msgid"):
        _validate_aibotid(frame, expected_aibotid)
        return frame
    raise ValueError("callback missing message body")


def _validate_aibotid(msg: dict, expected_aibotid: str = "") -> None:
    """校验智能机器人消息体中的 aibotid

    参数:
        msg: 智能机器人消息体
        expected_aibotid: 配置中的 BotID；为空时跳过校验

    返回:
        None
    """
    if not expected_aibotid:
        return
    actual_aibotid = msg.get("aibotid", "")
    if actual_aibotid and actual_aibotid != expected_aibotid:
        raise ValueError("callback aibotid mismatch")


class _session_scope:
    """兼容 async_sessionmaker 和测试会话工厂的异步上下文管理器"""

    def __init__(self, db_session_factory):
        """初始化会话上下文管理器

        参数:
            db_session_factory: 返回 AsyncSession 或异步上下文管理器的工厂
        """
        self._factory = db_session_factory
        self._ctx = None
        self._session = None

    async def __aenter__(self):
        """进入数据库会话上下文

        返回:
            AsyncSession: 当前数据库会话
        """
        candidate = self._factory()
        if inspect.isawaitable(candidate):
            candidate = await candidate
        if hasattr(candidate, "__aenter__"):
            self._ctx = candidate
            self._session = await candidate.__aenter__()
        else:
            self._session = candidate
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        """退出数据库会话上下文

        参数:
            exc_type: 异常类型
            exc: 异常对象
            tb: traceback 对象
        """
        if self._ctx is not None:
            return await self._ctx.__aexit__(exc_type, exc, tb)
        return None
