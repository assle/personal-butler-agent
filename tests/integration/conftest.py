"""
PostgreSQL 集成测试 fixtures
仅在 TEST_DATABASE_URL 环境变量配置时才启用
"""
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest_asyncio.fixture
async def postgres_engine():
    """提供显式配置的 PostgreSQL 集成测试引擎

    产出:
        AsyncEngine: 指向一次性测试数据库的异步引擎
    """
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    engine = create_async_engine(url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def postgres_schema(postgres_engine):
    """创建并清空 PostgreSQL 表结构"""
    from src.db.base import Base
    async with postgres_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture
async def postgres_session(postgres_engine, postgres_schema):
    """提供每个测试自动回滚的 PostgreSQL 会话

    产出:
        AsyncSession: 绑定外层回滚事务的异步会话
    """
    async with postgres_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest_asyncio.fixture
async def redis_client():
    import os
    from redis.asyncio import Redis
    url = os.getenv("REDIS_URL", "")
    if not url.startswith("redis://"):
        pytest.skip("REDIS_URL is required for Redis integration tests")
    client = Redis.from_url(url, decode_responses=True)
    await client.ping()
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def postgres_session_factory(postgres_engine, postgres_schema):
    """提供并发 PostgreSQL 会话工厂

    产出:
        async_sessionmaker: 可创建独立事务的会话工厂
    """
    return async_sessionmaker(
        postgres_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
