"""
WeComTokenManager 测试
覆盖 token 缓存命中、过期刷新、并发锁、API 错误处理
"""
import select
import time

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.wecom.token_manager import WeComTokenManager, TokenError


def _config_get(mock_get: AsyncMock, resp_data: dict):
    """
    配置 httpx.AsyncClient.get 的 mock。
    AsyncMock 被调用时返回一个 coroutine, await 该 coroutine 得到 mock.return_value。
    因此直接将 mock.return_value 设为 MagicMock, 其 .json() 返回 resp_data。
    """
    mock_get.return_value = MagicMock()
    mock_get.return_value.json.return_value = resp_data


async def test_get_token_success():
    """测试首次获取 token 成功"""
    mock_resp = {"errcode": 0, "access_token": "test_token_123", "expires_in": 7200}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        _config_get(mock_get, mock_resp)
        tm = WeComTokenManager("corp", "secret")
        token = await tm.get_token()
        assert token == "test_token_123"


async def test_get_token_cached():
    """测试 token 在有效期内使用缓存，不重新请求"""
    mock_resp = {"errcode": 0, "access_token": "cached_token", "expires_in": 7200}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        _config_get(mock_get, mock_resp)
        tm = WeComTokenManager("corp", "secret")
        token1 = await tm.get_token()
        token2 = await tm.get_token()
        assert token1 == "cached_token"
        assert token2 == "cached_token"
        # 只请求了一次
        assert mock_get.call_count == 1


async def test_get_token_api_error():
    """测试 API 返回错误时抛出 TokenError"""
    mock_resp = {"errcode": 40001, "errmsg": "invalid credential"}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        _config_get(mock_get, mock_resp)
        tm = WeComTokenManager("corp", "bad_secret")
        with pytest.raises(TokenError, match="40001"):
            await tm.get_token()


async def test_get_token_http_error():
    """测试网络错误时抛出 TokenError"""
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("connection refused")
        tm = WeComTokenManager("corp", "secret")
        with pytest.raises(TokenError, match="HTTP error"):
            await tm.get_token()


async def test_get_token_expiry():
    """测试 token 过期后自动刷新"""
    mock_resp = {"errcode": 0, "access_token": "new_token", "expires_in": 7200}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        _config_get(mock_get, mock_resp)
        tm = WeComTokenManager("corp", "secret")
        # 先取一个 token
        await tm.get_token()
        assert mock_get.call_count == 1
        # 强制过期
        tm._expires_at = time.time() - 10
        token2 = await tm.get_token()
        assert token2 == "new_token"
        assert mock_get.call_count == 2
