"""
WeComUserService 测试
覆盖缓存命中、过期刷新、userid 不存在、API 错误回退过期缓存
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select
from src.models.wecom_user import WeComUser
from src.wecom.user_service import WeComUserService


@pytest.fixture
def mock_token_manager():
    """创建模拟的 WeComTokenManager"""
    tm = AsyncMock()
    tm.get_token.return_value = "mock_token"
    return tm


async def test_cache_hit(db_session, mock_token_manager):
    """测试缓存命中，不调 API 直接返回"""
    # 预写入缓存
    cached = WeComUser(
        userid="zhangsan", name="张三",
        last_synced_at="2026-06-02T10:00:00+00:00",
    )
    db_session.add(cached)
    await db_session.flush()

    svc = WeComUserService(mock_token_manager)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        result = await svc.get_user("zhangsan", db_session)
        assert result is not None
        assert result.name == "张三"
        # 未调 API
        mock_get.assert_not_called()


async def test_cache_miss_fetch_from_api(db_session, mock_token_manager):
    """测试缓存未命中，调 API 获取并写入缓存"""
    api_resp = {
        "errcode": 0,
        "userid": "zhangsan",
        "name": "张三",
        "department": [1, 2],
        "avatar": "http://avatar.url",
        "position": "工程师",
        "mobile": "13800138000",
        "email": "zhangsan@example.com",
    }
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # 使用 MagicMock 作为 resp，与 token_manager 测试的 _config_get 模式一致
        mock_get.return_value = MagicMock()
        mock_get.return_value.json.return_value = api_resp
        svc = WeComUserService(mock_token_manager)
        result = await svc.get_user("zhangsan", db_session)
        assert result is not None
        assert result.name == "张三"
        assert result.position == "工程师"
        assert result.department == '[1, 2]'

    # 验证写入 DB
    stmt = select(WeComUser).where(WeComUser.userid == "zhangsan")
    db_result = await db_session.execute(stmt)
    saved = db_result.scalar_one()
    assert saved.name == "张三"


async def test_user_not_found_in_api(db_session, mock_token_manager):
    """测试 userid 在企微不存在时返回 None"""
    api_resp = {"errcode": 60111, "errmsg": "userid not found"}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MagicMock()
        mock_get.return_value.json.return_value = api_resp
        svc = WeComUserService(mock_token_manager)
        result = await svc.get_user("nobody", db_session)
        assert result is None


async def test_api_error_fallback_to_stale_cache(db_session, mock_token_manager):
    """测试 API 调用失败时回退返回过期缓存"""
    # 预写入过期缓存
    stale = WeComUser(
        userid="zhangsan", name="旧名称",
        last_synced_at="2020-01-01T00:00:00+00:00",
    )
    db_session.add(stale)
    await db_session.flush()

    svc = WeComUserService(mock_token_manager)
    # API 调用失败（token 获取失败）
    mock_token_manager.get_token.side_effect = Exception("token error")
    result = await svc.get_user("zhangsan", db_session)
    assert result is not None
    assert result.name == "旧名称"
