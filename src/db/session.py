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
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine
from src.config import settings


def enable_sqlite_foreign_keys(async_engine: AsyncEngine) -> None:
    """为 SQLite 异步引擎启用外键约束

    SQLite 默认关闭外键检查，需要在每个新连接建立时执行 PRAGMA。
    非 SQLite 数据库不需要该设置，因此直接跳过，避免影响未来数据库迁移。

    参数:
        async_engine: SQLAlchemy 异步数据库引擎

    返回:
        None；通过连接事件为 SQLite 引擎注册 PRAGMA 初始化逻辑
    """
    if async_engine.dialect.name != "sqlite":
        return

    @event.listens_for(async_engine.sync_engine, "connect")
    def _set_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        """在 SQLite 连接创建时打开外键约束

        参数:
            dbapi_connection: SQLAlchemy 提供的底层 DBAPI 连接
            _connection_record: SQLAlchemy 连接池记录，本函数不使用

        返回:
            None；通过 PRAGMA foreign_keys=ON 修改当前连接状态
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


engine = create_async_engine(settings.database_url, echo=False)
"""异步 SQLAlchemy 引擎，基于配置中的 database_url 创建"""
enable_sqlite_foreign_keys(engine)

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
