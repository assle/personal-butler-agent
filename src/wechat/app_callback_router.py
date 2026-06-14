"""
企业微信自建应用回调验证路由
提供接收消息服务器 URL 的 GET 验证和 POST 验签确认，不处理业务消息。

Workflow:
1. GET 校验签名、解密 echostr 并校验 CorpID
2. POST 解析 XML/JSON 密文、验签解密并确认明文结构
3. POST 不写数据库、不调用 Agent，只返回 success
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from src.wechat.callback_crypto import WeComCallbackCrypto

logger = logging.getLogger(__name__)


def create_app_callback_router(
    *,
    token: str,
    encoding_aes_key: str,
    corp_id: str,
) -> APIRouter:
    """创建企业微信自建应用回调验证路由

    参数:
        token: 接收消息服务器配置中的 Token
        encoding_aes_key: 接收消息服务器配置中的 EncodingAESKey
        corp_id: 企业 CorpID，用于校验加密载荷接收方

    返回:
        APIRouter: 可挂载到 FastAPI 应用的回调路由
    """
    router = APIRouter(prefix="/api/wechat/app", tags=["wechat-app"])
    crypto = WeComCallbackCrypto(token, encoding_aes_key, corp_id)

    @router.get("/callback")
    async def verify_callback(
        msg_signature: str,
        timestamp: str,
        nonce: str,
        echostr: str,
    ) -> PlainTextResponse:
        """验证企业微信接收消息服务器 URL

        参数:
            msg_signature: 企业微信回调签名
            timestamp: 签名时间戳
            nonce: 签名随机串
            echostr: 加密回显字符串

        返回:
            PlainTextResponse: 解密后的回显明文
        """
        try:
            plain = crypto.decrypt_if_signature_valid(
                msg_signature,
                timestamp,
                nonce,
                echostr,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("WeCom app callback verification rejected")
            raise HTTPException(status_code=403, detail="invalid callback") from exc
        return PlainTextResponse(plain)

    @router.post("/callback")
    async def receive_callback(
        request: Request,
        msg_signature: str = "",
        timestamp: str = "",
        nonce: str = "",
    ) -> PlainTextResponse:
        """验签并确认自建应用 POST 回调，但不处理业务消息

        参数:
            request: FastAPI 请求对象
            msg_signature: 企业微信回调签名
            timestamp: 签名时间戳
            nonce: 签名随机串

        返回:
            PlainTextResponse: 固定 success 确认
        """
        try:
            encrypted = _extract_encrypted_payload(await request.body())
        except (ET.ParseError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid callback body") from exc

        try:
            plain = crypto.decrypt_if_signature_valid(
                msg_signature,
                timestamp,
                nonce,
                encrypted,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("WeCom app POST callback rejected")
            raise HTTPException(status_code=403, detail="invalid callback") from exc

        try:
            payload_format = _validate_plain_payload(plain)
        except (ET.ParseError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="invalid callback payload") from exc

        logger.info(
            "WeCom app callback accepted: payload_format=%s",
            payload_format,
        )
        return PlainTextResponse("success")

    return router


def register_app_callback_router(
    app: FastAPI,
    *,
    token: str,
    encoding_aes_key: str,
    corp_id: str,
) -> bool:
    """配置完整时向 FastAPI 注册自建应用回调路由

    参数:
        app: FastAPI 应用
        token: 自建应用回调 Token
        encoding_aes_key: 自建应用回调 EncodingAESKey
        corp_id: 企业 CorpID

    返回:
        bool: 已注册返回 True，配置不完整返回 False
    """
    if not token or not encoding_aes_key or not corp_id:
        return False
    app.include_router(
        create_app_callback_router(
            token=token,
            encoding_aes_key=encoding_aes_key,
            corp_id=corp_id,
        )
    )
    return True


def _extract_encrypted_payload(body: bytes) -> str:
    """从 XML 或 JSON 请求体提取密文

    参数:
        body: HTTP 请求体字节

    返回:
        str: 非空 Encrypt 字段
    """
    if not body:
        raise ValueError("empty callback body")
    text = body.decode("utf-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        root = ET.fromstring(text)
        parsed = {child.tag: child.text or "" for child in root}
    if not isinstance(parsed, dict):
        raise ValueError("callback body must be an object")
    encrypted = str(parsed.get("Encrypt") or parsed.get("encrypt") or "").strip()
    if not encrypted:
        raise ValueError("callback body missing Encrypt")
    return encrypted


def _validate_plain_payload(plain: str) -> str:
    """确认解密后的明文是 XML 或 JSON

    参数:
        plain: 解密后的消息明文

    返回:
        str: xml 或 json
    """
    text = plain.strip()
    if not text:
        raise ValueError("empty callback payload")
    try:
        json.loads(text)
        return "json"
    except json.JSONDecodeError:
        ET.fromstring(text)
        return "xml"
