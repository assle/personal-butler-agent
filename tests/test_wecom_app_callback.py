"""
企业微信自建应用回调测试
验证 URL 回显、CorpID 校验和仅验签不处理业务的 POST 回调。
"""
import base64
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.wechat.callback_crypto import WeComCallbackCrypto
from src.wechat.app_callback_router import (
    create_app_callback_router,
    register_app_callback_router,
)


def _valid_encoding_aes_key() -> str:
    """生成测试用 EncodingAESKey；无输入参数；返回 43 位 Base64 字符串。"""
    return base64.b64encode(b"2" * 32).decode().rstrip("=")


def _create_app(*, corp_id: str = "ww-test-corp") -> FastAPI:
    """创建挂载自建应用回调路由的测试应用；输入 CorpID；返回 FastAPI。"""
    app = FastAPI()
    app.include_router(
        create_app_callback_router(
            token="callback-token",
            encoding_aes_key=_valid_encoding_aes_key(),
            corp_id=corp_id,
        )
    )
    return app


@pytest.mark.parametrize(
    ("token", "encoding_aes_key", "corp_id"),
    [
        ("", "aes-key", "ww-test-corp"),
        ("callback-token", "", "ww-test-corp"),
        ("callback-token", "aes-key", ""),
    ],
)
def test_app_callback_route_is_not_registered_with_incomplete_config(
    token: str,
    encoding_aes_key: str,
    corp_id: str,
):
    """验证配置不完整时不注册路由；输入三项配置；无返回值。"""
    app = FastAPI()

    registered = register_app_callback_router(
        app,
        token=token,
        encoding_aes_key=encoding_aes_key,
        corp_id=corp_id,
    )

    assert registered is False
    assert "/api/wechat/app/callback" not in {
        route.path for route in app.routes
    }


def test_app_callback_route_is_registered_with_complete_config():
    """验证配置完整时注册 GET/POST 路由；无输入参数；无返回值。"""
    app = FastAPI()

    registered = register_app_callback_router(
        app,
        token="callback-token",
        encoding_aes_key=_valid_encoding_aes_key(),
        corp_id="ww-test-corp",
    )

    callback_routes = [
        route
        for route in app.routes
        if route.path == "/api/wechat/app/callback"
    ]
    assert registered is True
    assert {method for route in callback_routes for method in route.methods} >= {
        "GET",
        "POST",
    }


@pytest.mark.asyncio
async def test_app_callback_get_returns_decrypted_echo():
    """验证合法 GET 回调返回解密回显；无输入参数；无返回值。"""
    crypto = WeComCallbackCrypto(
        "callback-token",
        _valid_encoding_aes_key(),
        "ww-test-corp",
    )
    encrypted = crypto.encrypt("verified-echo", "123", "nonce-get")
    transport = ASGITransport(app=_create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/wechat/app/callback",
            params={
                "msg_signature": encrypted.signature,
                "timestamp": "123",
                "nonce": "nonce-get",
                "echostr": encrypted.encrypt,
            },
        )

    assert response.status_code == 200
    assert response.text == "verified-echo"
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.asyncio
async def test_app_callback_get_rejects_invalid_signature():
    """验证 GET 回调拒绝错误签名；无输入参数；无返回值。"""
    crypto = WeComCallbackCrypto(
        "callback-token",
        _valid_encoding_aes_key(),
        "ww-test-corp",
    )
    encrypted = crypto.encrypt("verified-echo", "123", "nonce-get")
    transport = ASGITransport(app=_create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/wechat/app/callback",
            params={
                "msg_signature": "invalid",
                "timestamp": "123",
                "nonce": "nonce-get",
                "echostr": encrypted.encrypt,
            },
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_app_callback_get_rejects_wrong_corp_id():
    """验证 GET 回调拒绝密文中的错误 CorpID；无输入参数；无返回值。"""
    wrong_crypto = WeComCallbackCrypto(
        "callback-token",
        _valid_encoding_aes_key(),
        "ww-other-corp",
    )
    encrypted = wrong_crypto.encrypt("verified-echo", "123", "nonce-get")
    transport = ASGITransport(app=_create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/wechat/app/callback",
            params={
                "msg_signature": encrypted.signature,
                "timestamp": "123",
                "nonce": "nonce-get",
                "echostr": encrypted.encrypt,
            },
        )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapper", ["xml", "json"])
async def test_app_callback_post_accepts_encrypted_payload(wrapper: str):
    """验证 POST 接受 XML/JSON 密文；输入包装格式；无返回值。"""
    crypto = WeComCallbackCrypto(
        "callback-token",
        _valid_encoding_aes_key(),
        "ww-test-corp",
    )
    plain_message = (
        "<xml><ToUserName>ww-test-corp</ToUserName>"
        "<FromUserName>user-1</FromUserName><MsgType>text</MsgType></xml>"
    )
    encrypted = crypto.encrypt(plain_message, "456", "nonce-post")
    if wrapper == "xml":
        content = (
            "<xml><Encrypt><![CDATA["
            f"{encrypted.encrypt}"
            "]]></Encrypt></xml>"
        )
        request_kwargs = {"content": content}
    else:
        request_kwargs = {"json": {"encrypt": encrypted.encrypt}}
    transport = ASGITransport(app=_create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/wechat/app/callback",
            params={
                "msg_signature": encrypted.signature,
                "timestamp": "456",
                "nonce": "nonce-post",
            },
            **request_kwargs,
        )

    assert response.status_code == 200
    assert response.text == "success"


@pytest.mark.asyncio
async def test_app_callback_post_accepts_encrypted_json_plaintext():
    """验证 POST 接受解密后为 JSON 的消息；无输入参数；无返回值。"""
    crypto = WeComCallbackCrypto(
        "callback-token",
        _valid_encoding_aes_key(),
        "ww-test-corp",
    )
    encrypted = crypto.encrypt(
        json.dumps({"MsgType": "event", "Event": "change_contact"}),
        "789",
        "nonce-json",
    )
    transport = ASGITransport(app=_create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/wechat/app/callback",
            params={
                "msg_signature": encrypted.signature,
                "timestamp": "789",
                "nonce": "nonce-json",
            },
            json={"Encrypt": encrypted.encrypt},
        )

    assert response.status_code == 200
    assert response.text == "success"


@pytest.mark.asyncio
async def test_app_callback_post_rejects_missing_encrypt():
    """验证 POST 拒绝缺少密文的请求；无输入参数；无返回值。"""
    transport = ASGITransport(app=_create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/wechat/app/callback",
            params={
                "msg_signature": "unused",
                "timestamp": "456",
                "nonce": "nonce-post",
            },
            json={"MsgType": "text"},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_app_callback_post_rejects_invalid_signature():
    """验证 POST 拒绝错误签名；无输入参数；无返回值。"""
    crypto = WeComCallbackCrypto(
        "callback-token",
        _valid_encoding_aes_key(),
        "ww-test-corp",
    )
    encrypted = crypto.encrypt("<xml><MsgType>text</MsgType></xml>", "456", "nonce-post")
    transport = ASGITransport(app=_create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/wechat/app/callback",
            params={
                "msg_signature": "invalid",
                "timestamp": "456",
                "nonce": "nonce-post",
            },
            json={"Encrypt": encrypted.encrypt},
        )

    assert response.status_code == 403
