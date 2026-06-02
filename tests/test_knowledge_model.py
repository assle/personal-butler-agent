"""
知识库 ORM 模型测试
验证知识库文档和切块模型正确注册到 SQLAlchemy metadata

Workflow:
  导入 src.models → Base.metadata 收集 ORM 表 → 断言知识库表和索引存在
"""
from datetime import UTC, datetime

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
        title="健身原则",
        source="fitness.md",
        scope_type="public",
        scope_id=None,
        domain="fitness",
        checksum="abc123",
        created_by="user_a",
        created_at=now,
        updated_at=now,
    )

    assert doc.__tablename__ == "knowledge_documents"
    assert doc.title == "健身原则"
    assert doc.scope_type == "public"
    assert doc.scope_id is None
    assert doc.domain == "fitness"


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
        content="训练计划应逐步增加负荷。",
        scope_type="public",
        scope_id=None,
        domain="fitness",
        token_count=12,
        source="fitness.md",
        created_at=now,
    )

    assert chunk.__tablename__ == "knowledge_chunks"
    assert chunk.document_id == 1
    assert chunk.chunk_index == 0
    assert chunk.content == "训练计划应逐步增加负荷。"
