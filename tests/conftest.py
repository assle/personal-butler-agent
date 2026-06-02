"""
测试配置和共享 fixtures
提供 mock_llm、db_session、db_engine、http_client 等可复用的 pytest fixture

Workflow:
  测试文件通过 fixture 参数名引用这些 fixture → pytest 自动注入
  mock_llm: 模拟 LLM 客户端，避免实际 API 调用
  db_session: 每个测试独立的 SQLite 内存数据库
  http_client: 基于 FastAPI TestClient 的异步 HTTP 客户端
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.db.base import Base
from src.db.session import enable_sqlite_foreign_keys

# 导入 models 模块以触发 ORM 类注册到 Base.metadata
import src.models  # noqa: F401


@pytest.fixture
def mock_llm():
    """创建模拟的 LLM 客户端，避免测试中调用实际 API

    返回:
        AsyncMock: 可配置返回值的 mock 对象，支持 .chat() 和 .chat_json() 方法
    """
    return AsyncMock()


@pytest_asyncio.fixture
async def db_session():
    """创建独立的 SQLite 内存数据库会话，测试后自动销毁

    每个测试拥有独立的数据库实例，数据不会泄漏到其他测试。

    产出:
        AsyncSession: SQLAlchemy 异步数据库会话
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    enable_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def db_engine():
    """创建独立的 SQLite 内存数据库引擎，产出引擎对象（非会话）

    用于需要直接操作引擎的测试场景。

    产出:
        AsyncEngine: SQLAlchemy 异步引擎
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    enable_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture
async def http_client():
    """创建基于 FastAPI TestClient 的异步 HTTP 客户端

    使用 ASGITransport 直接调用 app（不走网络），在测试前后自动创建和清理数据库。

    产出:
        AsyncClient: httpx 异步 HTTP 客户端
    """
    from src.main import app
    from src.db.base import Base
    from src.db.session import engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
