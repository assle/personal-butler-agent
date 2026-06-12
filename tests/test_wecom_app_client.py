"""
企微自建应用消息客户端测试
验证 token 缓存、open_userid 转换、业务错误和主动文本消息。
"""
from unittest.mock import AsyncMock

import pytest

from src.wechat.app_client import WeComAppApiError, WeComAppMessageClient


@pytest.mark.asyncio
async def test_client_reuses_cached_access_token():
    """缓存命中时不调用 gettoken"""
    cache = AsyncMock()
    cache.get.return_value = "cached-token"
    get_json = AsyncMock()
    client = WeComAppMessageClient(
        corp_id="ww-test",
        secret="secret",
        agent_id=1000002,
        cache=cache,
        get_json=get_json,
        post_json=AsyncMock(),
    )
    assert await client.get_access_token() == "cached-token"
    get_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_fetches_and_caches_access_token():
    """缓存未命中时获取 token，并以 expires_in-300 缓存"""
    cache = AsyncMock()
    cache.get.return_value = None
    get_json = AsyncMock(
        return_value={"errcode": 0, "access_token": "new-token", "expires_in": 7200}
    )
    client = WeComAppMessageClient(
        corp_id="ww-test",
        secret="secret",
        agent_id=1000002,
        cache=cache,
        get_json=get_json,
        post_json=AsyncMock(),
    )
    assert await client.get_access_token() == "new-token"
    cache.set.assert_awaited_once_with(
        "wecom:app:ww-test:1000002:access_token", "new-token", 6900
    )


@pytest.mark.asyncio
async def test_convert_open_userid_returns_plain_userid():
    """转换接口返回自建应用可发送的明文 userid"""
    cache = AsyncMock()
    cache.get.return_value = "token"
    post_json = AsyncMock(
        return_value={
            "errcode": 0,
            "userid_list": [{"open_userid": "open-u1", "userid": "u1"}],
            "invalid_open_userid_list": [],
        }
    )
    client = WeComAppMessageClient(
        corp_id="ww-test",
        secret="secret",
        agent_id=1000002,
        cache=cache,
        get_json=AsyncMock(),
        post_json=post_json,
    )
    assert await client.convert_open_userid("open-u1") == "u1"


@pytest.mark.asyncio
async def test_send_text_rejects_http_200_business_failure():
    """HTTP 200 但 errcode 非零时必须抛出业务异常"""
    cache = AsyncMock()
    cache.get.return_value = "token"
    client = WeComAppMessageClient(
        corp_id="ww-test",
        secret="secret",
        agent_id=1000002,
        cache=cache,
        get_json=AsyncMock(),
        post_json=AsyncMock(return_value={"errcode": 81013, "errmsg": "invalid user"}),
    )
    with pytest.raises(WeComAppApiError):
        await client.send_text("u1", "完成")


@pytest.mark.asyncio
async def test_send_text_rejects_invaliduser_and_unlicenseduser():
    """部分无效收件人也不能视为单用户投递成功"""
    cache = AsyncMock()
    cache.get.return_value = "token"
    for response in (
        {"errcode": 0, "invaliduser": "u1", "unlicenseduser": ""},
        {"errcode": 0, "invaliduser": "", "unlicenseduser": "u1"},
    ):
        client = WeComAppMessageClient(
            corp_id="ww-test",
            secret="secret",
            agent_id=1000002,
            cache=cache,
            get_json=AsyncMock(),
            post_json=AsyncMock(return_value=response),
        )
        with pytest.raises(WeComAppApiError):
            await client.send_text("u1", "完成")


@pytest.mark.asyncio
async def test_send_text_refreshes_expired_token_once():
    """token 失效业务码触发一次缓存清理和刷新"""
    cache = AsyncMock()
    cache.get.side_effect = ["expired-token", None]
    get_json = AsyncMock(
        return_value={"errcode": 0, "access_token": "fresh-token", "expires_in": 7200}
    )
    post_json = AsyncMock(
        side_effect=[
            {"errcode": 42001, "errmsg": "access_token expired"},
            {"errcode": 0, "errmsg": "ok", "msgid": "msg-1"},
        ]
    )
    client = WeComAppMessageClient(
        corp_id="ww-test",
        secret="secret",
        agent_id=1000002,
        cache=cache,
        get_json=get_json,
        post_json=post_json,
    )
    assert await client.send_text("u1", "完成") == "msg-1"
    cache.delete.assert_awaited_once()
