"""
数据库基础模块
提供 SQLAlchemy 声明式基类和异步会话工厂

在总流程中的位置:
  lifespan 启动 → engine 创建连接 → Base.metadata.create_all 建表
  请求处理 → Depends(get_db) → AsyncSession → 业务读写

Workflow:
  engine + async_session + get_db 依赖注入，贯穿整个请求生命周期
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from src.config import settings

engine = create_async_engine(settings.database_url, echo=False)
"""异步 SQLAlchemy 引擎，基于配置中的 database_url 创建"""

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
"""异步会话工厂，每个请求通过 get_db 获取独立会话"""


async def get_db():
    """FastAPI 依赖注入：为每个请求提供异步数据库会话

    作为 FastAPI Depends 使用，自动管理事务的提交和回滚。
    请求成功自动提交，异常时自动回滚，请求结束自动关闭会话。

    参数:
        无（由 FastAPI 依赖注入框架调用）

    产出:
        AsyncSession: 异步数据库会话对象
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
