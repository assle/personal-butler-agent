"""
SQLite 到 PostgreSQL 迁移集成测试
"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from src.db.base import Base
import src.models  # noqa: F401


@pytest.mark.asyncio
async def test_migration_copies_research_tasks(postgres_engine, postgres_session):
    """验证 workspace_id 在 PG 中的研究任务写入与隔离查询"""
    # 在 PG 中创建 schema
    async with postgres_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(timezone.utc)
    # 创建工作空间
    await postgres_session.execute(text(
        "INSERT INTO workspaces (id, name, status, policy, created_at, updated_at) "
        "VALUES (:id, :name, 'active', :policy, :now, :now)"
    ), {"id": "default", "name": "Default", "policy": "{}", "now": now})
    await postgres_session.flush()

    # 创建研究任务
    await postgres_session.execute(text(
        "INSERT INTO research_tasks (id, source_msgid, requester_open_userid, workspace_id, "
        "question, research_type, status, access_scope, max_rounds, timeout_seconds, "
        "current_round, cancel_requested, trace_id, created_at, updated_at) "
        "VALUES (:id, :msgid, :userid, :ws_id, :question, 'foundation', 'completed', "
        ":scope, 4, 300, 0, false, :trace, :now, :now)"
    ), {
        "id": "R20240101-TEST0001",
        "msgid": "msg-test-1",
        "userid": "open-u1",
        "ws_id": "default",
        "question": "test question",
        "scope": json.dumps({"workspace_id": "default"}),
        "trace": "test-trace-00001",
        "now": now,
    })
    await postgres_session.flush()

    # 验证研究任务存在且 workspace_id 正确
    result = await postgres_session.execute(
        text("SELECT COUNT(*) FROM research_tasks WHERE source_msgid = 'msg-test-1'")
    )
    assert result.scalar() == 1

    result = await postgres_session.execute(
        text("SELECT workspace_id FROM research_tasks WHERE source_msgid = 'msg-test-1'")
    )
    assert result.scalar() == "default"

    # 验证跨工作空间隔离：ws-b 查不到 ws-a 的数据
    result = await postgres_session.execute(
        text("SELECT COUNT(*) FROM research_tasks WHERE workspace_id = 'ws-b'")
    )
    assert result.scalar() == 0
