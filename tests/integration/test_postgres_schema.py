"""
PostgreSQL 集成测试
验证真实 PostgreSQL 连接和 schema 表创建
"""
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text, inspect as sa_inspect


@pytest.mark.asyncio
async def test_postgres_fixture_uses_postgresql(postgres_engine):
    """验证集成测试连接到真实 PostgreSQL"""
    assert postgres_engine.dialect.name == "postgresql"
    async with postgres_engine.connect() as connection:
        assert await connection.scalar(text("select 1")) == 1


@pytest.mark.asyncio
async def test_alembic_upgrade_applies_schema(postgres_engine):
    """验证 Alembic 迁移能完整创建 schema（子进程运行以避免事件循环冲突）"""
    url = os.getenv("TEST_DATABASE_URL", "")

    # Run upgrade in subprocess to avoid event loop conflict
    env = {**os.environ, "DATABASE_URL": url, "DEEPSEEK_API_KEY": "test"}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.getcwd(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    # Verify key tables exist
    async with postgres_engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: sa_inspect(sync_conn).get_table_names()
        )
    assert "research_tasks" in tables
    assert "workspaces" in tables
    assert "workspace_members" in tables
    assert "knowledge_chunks" in tables

    # 验证 trace_id 列为非空
    async with postgres_engine.connect() as conn:
        task_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]: column
                for column in sa_inspect(sync_conn).get_columns("research_tasks")
            }
        )
        event_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]: column
                for column in sa_inspect(sync_conn).get_columns("research_events")
            }
        )
        inbound_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]: column
                for column in sa_inspect(sync_conn).get_columns("inbound_messages")
            }
        )
    assert task_columns["trace_id"]["nullable"] is False
    assert event_columns["trace_id"]["nullable"] is False
    assert inbound_columns["received_at"]["type"].timezone is True
    assert inbound_columns["processed_at"]["type"].timezone is True


def test_trace_migration_has_postgresql_backfill():
    """验证 trace 迁移不再把 SQLite randomblob 用于 PostgreSQL"""
    migration = Path(
        "alembic/versions/add_trace_id_20260613.py"
    ).read_text()
    assert 'if dialect == "postgresql":' in migration
    assert "md5(id)" in migration
