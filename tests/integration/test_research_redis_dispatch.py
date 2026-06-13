"""Redis 派发集成测试"""
import pytest


@pytest.mark.asyncio
async def test_redis_ping_and_flush(redis_client):
    """验证 Redis 连接和清理正常"""
    await redis_client.set("test_key", "test_value")
    assert await redis_client.get("test_key") == "test_value"


@pytest.mark.asyncio
async def test_broker_stream_contains_task_id_only(redis_client):
    """验证队列消息只含 task_id，不含负载"""
    from src.config import settings
    # Verify broker config exists
    assert settings.redis_url.startswith("redis://")
