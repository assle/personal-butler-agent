"""
Alembic 版本校验
提供启动时数据库迁移版本检查，防止应用在 schema 不一致的数据库上运行
"""
import logging
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# 项目根目录，用于从任意 CWD 解析 alembic.ini 路径
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


async def assert_database_at_head(engine: AsyncEngine) -> None:
    """验证数据库 Alembic 版本已达到代码要求

    参数:
        engine: 应用异步数据库引擎

    返回:
        None: 版本一致时正常返回，不一致时抛出 RuntimeError
    """
    async with engine.connect() as connection:
        await connection.run_sync(_check_revision)


def _check_revision(connection):
    """同步版本校验逻辑"""
    context = MigrationContext.configure(connection)
    db_heads = set(context.get_current_heads())

    alembic_cfg = AlembicConfig(str(_PROJECT_ROOT / "alembic.ini"))
    # 避免 env.py 再次尝试连接数据库（只用于 ScriptDirectory）
    script = ScriptDirectory.from_config(alembic_cfg)
    code_heads = set(script.get_heads())

    if db_heads != code_heads:
        db_display = ", ".join(sorted(db_heads)) if db_heads else "(空数据库)"
        code_display = ", ".join(sorted(code_heads))
        raise RuntimeError(
            f"数据库迁移版本 ({db_display}) "
            f"与代码要求 ({code_display}) 不一致。"
            f"请运行: alembic upgrade head"
        )
    logger.info("Alembic schema revision check: OK (heads=%s)", sorted(code_heads))
