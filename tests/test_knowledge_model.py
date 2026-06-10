"""
知识库 ORM 模型测试
验证知识库文档和切块模型正确注册到 SQLAlchemy metadata

Workflow:
  导入 src.models → Base.metadata 收集 ORM 表 → 断言知识库表和索引存在
"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from src.db.base import Base
from src.models.knowledge import KnowledgeChunk, KnowledgeDocument


def test_knowledge_tables_registered():
    """验证知识库表已注册到 Base.metadata

    参数:
        无

    返回:
        None；通过断言确认 metadata 中包含两张知识库表
    """
    table_names = set(Base.metadata.tables)

    assert "knowledge_documents" in table_names
    assert "knowledge_chunks" in table_names


def test_knowledge_document_defaults():
    """验证 KnowledgeDocument 可以用最小字段创建

    参数:
        无

    返回:
        None；通过断言确认字段赋值符合预期
    """
    now = datetime.now(UTC).isoformat()
    doc = KnowledgeDocument(
        title="总结规范",
        source="summary.md",
        scope_type="public",
        scope_id=None,
        domain="summary",
        checksum="abc123",
        created_by="user_a",
        created_at=now,
        updated_at=now,
    )

    assert doc.__tablename__ == "knowledge_documents"
    assert doc.title == "总结规范"
    assert doc.scope_type == "public"
    assert doc.scope_id is None
    assert doc.domain == "summary"


def test_knowledge_chunk_defaults():
    """验证 KnowledgeChunk 可以用最小字段创建

    参数:
        无

    返回:
        None；通过断言确认 chunk 字段赋值符合预期
    """
    now = datetime.now(UTC).isoformat()
    chunk = KnowledgeChunk(
        document_id=1,
        chunk_index=0,
        content="总结应突出结论、行动项和风险。",
        scope_type="public",
        scope_id=None,
        domain="summary",
        token_count=12,
        source="summary.md",
        created_at=now,
    )

    assert chunk.__tablename__ == "knowledge_chunks"
    assert chunk.document_id == 1
    assert chunk.chunk_index == 0
    assert chunk.content == "总结应突出结论、行动项和风险。"


async def test_sqlite_foreign_keys_enabled(db_session):
    """验证测试数据库会话启用了 SQLite 外键约束

    参数:
        db_session: 测试用异步数据库会话

    返回:
        None；通过断言确认 PRAGMA foreign_keys 为 1
    """
    result = await db_session.execute(text("PRAGMA foreign_keys"))

    assert result.scalar_one() == 1


async def test_knowledge_chunk_requires_existing_document(db_session):
    """验证孤立知识库切块不能写入数据库

    参数:
        db_session: 测试用异步数据库会话

    返回:
        None；通过断言确认不存在的 document_id 会触发 IntegrityError
    """
    now = datetime.now(UTC).isoformat()
    db_session.add(
        KnowledgeChunk(
            document_id=999,
            chunk_index=0,
            content="不存在父文档的切块。",
            scope_type="public",
            scope_id=None,
            domain="summary",
            token_count=10,
            source="missing.md",
            created_at=now,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_raw_delete_knowledge_document_cascades_chunks(db_session):
    """验证原生 SQL 删除文档会级联删除知识库切块

    参数:
        db_session: 测试用异步数据库会话

    返回:
        None；通过断言确认 raw DELETE 后子表记录被级联删除
    """
    now = datetime.now(UTC).isoformat()
    document = KnowledgeDocument(
        title="总结规范",
        source="summary.md",
        scope_type="public",
        scope_id=None,
        domain="summary",
        checksum="abc123",
        created_by="user_a",
        created_at=now,
        updated_at=now,
    )
    document.chunks.append(
        KnowledgeChunk(
            chunk_index=0,
            content="总结应突出结论、行动项和风险。",
            scope_type="public",
            scope_id=None,
            domain="summary",
            token_count=12,
            source="summary.md",
            created_at=now,
        )
    )
    db_session.add(document)
    await db_session.flush()

    await db_session.execute(
        text("DELETE FROM knowledge_documents WHERE id = :document_id"),
        {"document_id": document.id},
    )
    await db_session.flush()

    result = await db_session.execute(
        select(func.count()).select_from(KnowledgeChunk)
    )
    assert result.scalar_one() == 0
