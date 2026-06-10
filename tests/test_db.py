"""
数据库模块测试
验证异步 SQLAlchemy 会话连接和 ORM 表注册

测试范围:
  - 内存数据库连接可用
  - ORM 模型正确注册到 Base.metadata
"""
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_session_connects(db_session):
    """验证数据库会话能正常执行 SQL 查询

    参数:
        db_session: conftest 提供的 SQLite 内存数据库会话 fixture
    """
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


@pytest.mark.asyncio
async def test_base_metadata_has_tables():
    """验证 ORM 模型正确注册到 Base.metadata

    参数:
        无

    返回:
        None；确认当前运行表已注册，退役表不再进入 ORM metadata
    """
    from src.db.base import Base

    table_names = set(Base.metadata.tables)
    assert {
        "group_messages",
        "knowledge_documents",
        "inbound_messages",
        "reminders",
    } <= table_names
    assert "training_records" not in table_names
    assert "user_preferences" not in table_names
