# RAG Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Stage 1 SQLite knowledge-base MVP with multi-tenant scope filtering and QAAgent RAG injection.

**Architecture:** Add a focused `src/knowledge/` service layer that owns document chunking, ingest, retrieval, and permission filtering. Store documents/chunks in SQLite through SQLAlchemy models, expose one `KnowledgeService.search()` method to agents, and connect QAAgent through a new `retrieve_knowledge` graph node.

**Tech Stack:** Python 3.13+, FastAPI, LangGraph, SQLAlchemy 2 async, SQLite, pytest, uv.

---

## File Structure

- Create `src/models/knowledge.py`: SQLAlchemy ORM models for `knowledge_documents` and `knowledge_chunks`.
- Modify `src/models/__init__.py`: import knowledge models so `Base.metadata.create_all` creates the new tables.
- Create `src/knowledge/__init__.py`: export knowledge service symbols.
- Create `src/knowledge/schemas.py`: small dataclasses/enums for scope, domain, chunks, ingest input, and search results.
- Create `src/knowledge/chunking.py`: deterministic `.md` / `.txt` chunking helpers.
- Create `src/knowledge/service.py`: ingest and search service with centralized scope/domain filtering.
- Create `scripts/ingest_knowledge.py`: local CLI for importing `.md` / `.txt` documents into SQLite.
- Modify `src/agents/registry.py`: allow optional `extra_state` in the agent protocol.
- Modify `src/agents/base.py`: document optional `extra_state` in the base interface.
- Modify `src/agents/qa/state.py`: add chat and knowledge fields to QA state.
- Modify `src/agents/qa/nodes.py`: add `retrieve_knowledge` and inject retrieved chunks into QA prompt.
- Modify `src/agents/qa/graph.py`: add the retrieval node and accept optional `extra_state`.
- Modify `src/router/debug.py`: pass `chat_type` and `chat_id` to agents.
- Modify `src/wechat/router.py` and `src/wechat/robot_router.py`: pass chat metadata through `extra_state` where the selected agent supports it.
- Create `tests/test_knowledge_model.py`: model/table registration tests.
- Create `tests/test_knowledge_chunking.py`: chunking behavior tests.
- Create `tests/test_knowledge_service.py`: ingest, retrieval, permissions, and domain filtering tests.
- Modify `tests/test_qa.py`: verify QAAgent injects knowledge context and survives retrieval errors.
- Modify `docs/agent/active-context.md`: mark the Stage 1 knowledge MVP as implemented after code is complete.
- Modify `docs/agent/patterns.md`: add the knowledge-service pattern after code is complete.
- Modify `docs/agent/upgrade-roadmap.md`: mark the Stage 1 portion of RAG as complete after code is complete.

## Task 1: Knowledge ORM Models

**Files:**
- Create: `src/models/knowledge.py`
- Modify: `src/models/__init__.py`
- Test: `tests/test_knowledge_model.py`

- [ ] **Step 1: Write model registration tests**

Create `tests/test_knowledge_model.py`:

```python
"""
知识库 ORM 模型测试
验证知识库文档和切块模型正确注册到 SQLAlchemy metadata

Workflow:
  导入 src.models → Base.metadata 收集 ORM 表 → 断言知识库表和索引存在
"""
from datetime import datetime, UTC

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
```

- [ ] **Step 2: Run model tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_knowledge_model.py -q
```

Expected: FAIL because `src.models.knowledge` does not exist.

- [ ] **Step 3: Create knowledge models**

Create `src/models/knowledge.py`:

```python
"""
知识库 ORM 模型
定义知识库文档和文档切块两张 SQLite 表，用于 RAG 检索

Workflow:
  文档导入 → KnowledgeDocument 记录来源和权限 → KnowledgeChunk 保存可检索片段
  → KnowledgeService 按 scope/domain 过滤后检索 chunk
"""
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class KnowledgeDocument(Base):
    """知识库文档表，记录文档来源、权限范围和领域标签"""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_documents_scope_domain", "scope_type", "scope_id", "domain"),
        Index("ix_knowledge_documents_checksum", "checksum"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class KnowledgeChunk(Base):
    """知识库切块表，保存可检索的文本片段和冗余权限字段"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("ix_knowledge_chunks_document_order", "document_id", "chunk_index"),
        Index("ix_knowledge_chunks_scope_domain", "scope_type", "scope_id", "domain"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
```

- [ ] **Step 4: Register models in package init**

Modify `src/models/__init__.py`:

```python
"""ORM 模型包，包含 SQLite 数据表映射"""
from src.models.training import TrainingRecord
from src.models.preference import UserPreference
from src.models.group_message import GroupMessage
from src.models.conversation import ConversationMessage, ConversationSummary
from src.models.knowledge import KnowledgeDocument, KnowledgeChunk

__all__ = [
    "TrainingRecord",
    "UserPreference",
    "GroupMessage",
    "ConversationMessage",
    "ConversationSummary",
    "KnowledgeDocument",
    "KnowledgeChunk",
]
```

- [ ] **Step 5: Run model tests and verify they pass**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_knowledge_model.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/models/knowledge.py src/models/__init__.py tests/test_knowledge_model.py
git commit -m "feat: add knowledge base ORM models"
```

## Task 2: Knowledge Schemas and Chunking

**Files:**
- Create: `src/knowledge/__init__.py`
- Create: `src/knowledge/schemas.py`
- Create: `src/knowledge/chunking.py`
- Test: `tests/test_knowledge_chunking.py`

- [ ] **Step 1: Write chunking tests**

Create `tests/test_knowledge_chunking.py`:

```python
"""
知识库切块测试
验证 Markdown/TXT 文档可以被稳定切成适合检索的文本片段

Workflow:
  原始文本 → chunk_text() → 带标题上下文的 KnowledgeChunkInput 列表
"""
from src.knowledge.chunking import chunk_text


def test_chunk_text_keeps_markdown_heading_context():
    """验证 Markdown 标题会作为上下文进入 chunk

    参数:
        无

    返回:
        None；通过断言确认 chunk 内容包含标题和正文
    """
    text = "# 健身原则\n\n逐步增加负荷。\n\n保持动作标准。"

    chunks = chunk_text(text, max_chars=40)

    assert len(chunks) == 1
    assert chunks[0].content.startswith("# 健身原则")
    assert "逐步增加负荷" in chunks[0].content
    assert "保持动作标准" in chunks[0].content


def test_chunk_text_splits_long_paragraph_groups():
    """验证超出长度限制的段落组会被拆分

    参数:
        无

    返回:
        None；通过断言确认切块数量和序号稳定
    """
    text = "第一段内容很长。\n\n第二段内容也很长。\n\n第三段内容继续很长。"

    chunks = chunk_text(text, max_chars=16)

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert chunks[0].content == "第一段内容很长。"
    assert chunks[1].content == "第二段内容也很长。"
    assert chunks[2].content == "第三段内容继续很长。"


def test_chunk_text_drops_blank_input():
    """验证空白输入不会生成 chunk

    参数:
        无

    返回:
        None；通过断言确认空白文本返回空列表
    """
    assert chunk_text(" \n\n\t ") == []
```

- [ ] **Step 2: Run chunking tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_knowledge_chunking.py -q
```

Expected: FAIL because `src.knowledge.chunking` does not exist.

- [ ] **Step 3: Create knowledge schemas**

Create `src/knowledge/schemas.py`:

```python
"""
知识库数据结构
定义知识库导入、切块和检索结果使用的轻量结构

Workflow:
  chunking.py 生成 KnowledgeChunkInput → service.py 入库
  service.py 检索 KnowledgeChunk → 返回 KnowledgeChunkResult 给 agent
"""
from dataclasses import dataclass

VALID_SCOPE_TYPES = {"public", "user", "group"}
VALID_DOMAINS = {"global", "qa", "fitness", "meal", "summary"}


@dataclass(frozen=True)
class KnowledgeChunkInput:
    """待入库的知识切块"""

    chunk_index: int
    content: str
    token_count: int


@dataclass(frozen=True)
class KnowledgeChunkResult:
    """知识库检索结果，供 agent 注入 prompt"""

    content: str
    title: str
    source: str
    score: float
    scope_type: str
    domain: str


@dataclass(frozen=True)
class KnowledgeIngestRequest:
    """知识库文档导入请求"""

    title: str
    source: str
    content: str
    scope_type: str
    scope_id: str | None
    domain: str
    created_by: str | None = None
```

- [ ] **Step 4: Create chunking helper**

Create `src/knowledge/chunking.py`:

```python
"""
知识库文档切块工具
将 Markdown/TXT 文本按段落聚合成稳定 chunk，供 KnowledgeService 入库

Workflow:
  文档文本 → 去除空白段落 → 跟踪 Markdown 标题 → 按 max_chars 聚合 → KnowledgeChunkInput
"""
from src.knowledge.schemas import KnowledgeChunkInput


def _estimate_tokens(text: str) -> int:
    """估算文本 token 数

    参数:
        text: 待估算文本

    返回:
        int: 粗略 token 数，用于记录 chunk 大小
    """
    return max(1, len(text) // 2)


def chunk_text(text: str, max_chars: int = 800) -> list[KnowledgeChunkInput]:
    """将文档文本切成 chunk

    参数:
        text: Markdown 或 TXT 文档文本
        max_chars: 每个 chunk 的目标最大字符数

    返回:
        list[KnowledgeChunkInput]: 按原文顺序排列的切块列表
    """
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current_parts: list[str] = []
    current_heading = ""

    for paragraph in paragraphs:
        if paragraph.startswith("#"):
            current_heading = paragraph

        candidate_parts = [*current_parts, paragraph]
        candidate = "\n\n".join(candidate_parts)
        if current_parts and len(candidate) > max_chars:
            chunks.append("\n\n".join(current_parts))
            current_parts = []
            if current_heading and not paragraph.startswith("#"):
                current_parts.append(current_heading)
        current_parts.append(paragraph)

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return [
        KnowledgeChunkInput(
            chunk_index=index,
            content=chunk,
            token_count=_estimate_tokens(chunk),
        )
        for index, chunk in enumerate(chunks)
        if chunk.strip()
    ]
```

- [ ] **Step 5: Create package export**

Create `src/knowledge/__init__.py`:

```python
"""知识库模块包，提供文档切块、入库和检索服务"""
from src.knowledge.schemas import (
    KnowledgeChunkInput,
    KnowledgeChunkResult,
    KnowledgeIngestRequest,
)
from src.knowledge.chunking import chunk_text

__all__ = [
    "KnowledgeChunkInput",
    "KnowledgeChunkResult",
    "KnowledgeIngestRequest",
    "chunk_text",
]
```

- [ ] **Step 6: Run chunking tests and verify they pass**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_knowledge_chunking.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/knowledge/__init__.py src/knowledge/schemas.py src/knowledge/chunking.py tests/test_knowledge_chunking.py
git commit -m "feat: add knowledge chunking"
```

## Task 3: KnowledgeService Ingest and Search

**Files:**
- Create: `src/knowledge/service.py`
- Test: `tests/test_knowledge_service.py`

- [ ] **Step 1: Write service tests**

Create `tests/test_knowledge_service.py`:

```python
"""
知识库服务测试
验证文档入库、scope 权限过滤、domain 过滤和关键词检索

Workflow:
  KnowledgeService.ingest() 写入文档和 chunk → search() 按用户/群聊权限返回结果
"""
import pytest

from src.knowledge.schemas import KnowledgeIngestRequest
from src.knowledge.service import KnowledgeService


@pytest.mark.asyncio
async def test_search_returns_public_knowledge(db_session):
    """验证任何用户都能检索 public 知识

    参数:
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 public chunk 可见
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="公共健身知识",
            source="public.md",
            content="深蹲时要保持核心稳定。",
            scope_type="public",
            scope_id=None,
            domain="qa",
            created_by="admin",
        ),
        db_session,
    )

    results = await service.search(
        query="深蹲",
        user_id="user_a",
        chat_type="single",
        chat_id=None,
        domains=["global", "qa"],
        db=db_session,
    )

    assert len(results) == 1
    assert results[0].title == "公共健身知识"
    assert "核心稳定" in results[0].content


@pytest.mark.asyncio
async def test_user_private_scope_is_isolated(db_session):
    """验证用户只能检索自己的私有知识

    参数:
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 user scope 不越权
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="A 的资料",
            source="a.md",
            content="用户 A 喜欢低碳饮食。",
            scope_type="user",
            scope_id="user_a",
            domain="qa",
            created_by="user_a",
        ),
        db_session,
    )
    await service.ingest(
        KnowledgeIngestRequest(
            title="B 的资料",
            source="b.md",
            content="用户 B 喜欢高碳饮食。",
            scope_type="user",
            scope_id="user_b",
            domain="qa",
            created_by="user_b",
        ),
        db_session,
    )

    results = await service.search(
        query="饮食",
        user_id="user_a",
        chat_type="single",
        chat_id=None,
        domains=["qa"],
        db=db_session,
    )

    titles = {item.title for item in results}
    assert titles == {"A 的资料"}


@pytest.mark.asyncio
async def test_group_private_scope_is_isolated(db_session):
    """验证群聊只能检索本群私有知识

    参数:
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 group scope 不越权
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="群 A 项目资料",
            source="group-a.md",
            content="项目代号是青松。",
            scope_type="group",
            scope_id="chat_a",
            domain="qa",
            created_by="user_a",
        ),
        db_session,
    )
    await service.ingest(
        KnowledgeIngestRequest(
            title="群 B 项目资料",
            source="group-b.md",
            content="项目代号是海棠。",
            scope_type="group",
            scope_id="chat_b",
            domain="qa",
            created_by="user_b",
        ),
        db_session,
    )

    results = await service.search(
        query="项目代号",
        user_id="user_a",
        chat_type="group",
        chat_id="chat_a",
        domains=["qa"],
        db=db_session,
    )

    assert [item.title for item in results] == ["群 A 项目资料"]
    assert "青松" in results[0].content


@pytest.mark.asyncio
async def test_group_search_does_not_read_user_private_knowledge(db_session):
    """验证群聊检索不会读取发言人的个人私有知识

    参数:
        db_session: 测试数据库会话

    返回:
        None；通过断言确认群聊不混用 user scope
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="用户 A 私有资料",
            source="user-a.md",
            content="用户 A 的私人目标是增肌。",
            scope_type="user",
            scope_id="user_a",
            domain="qa",
            created_by="user_a",
        ),
        db_session,
    )

    results = await service.search(
        query="私人目标",
        user_id="user_a",
        chat_type="group",
        chat_id="chat_a",
        domains=["qa"],
        db=db_session,
    )

    assert results == []


@pytest.mark.asyncio
async def test_domain_filter_blocks_unrelated_chunks(db_session):
    """验证 domain 过滤会排除不相关领域知识

    参数:
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 QA 检索不会拿到 fitness-only chunk
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="健身专用资料",
            source="fitness.md",
            content="训练计划需要渐进超负荷。",
            scope_type="public",
            scope_id=None,
            domain="fitness",
            created_by="admin",
        ),
        db_session,
    )

    results = await service.search(
        query="训练计划",
        user_id="user_a",
        chat_type="single",
        chat_id=None,
        domains=["qa"],
        db=db_session,
    )

    assert results == []
```

- [ ] **Step 2: Run service tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_knowledge_service.py -q
```

Expected: FAIL because `src.knowledge.service` does not exist.

- [ ] **Step 3: Implement KnowledgeService**

Create `src/knowledge/service.py`:

```python
"""
知识库服务
封装文档入库和检索逻辑，集中处理 scope/domain 权限过滤

Workflow:
  ingest() 校验请求 → 切块 → 写入 KnowledgeDocument/KnowledgeChunk
  search() 构造可见范围 → 查询候选 chunk → 关键词评分 → 返回 KnowledgeChunkResult
"""
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge.chunking import chunk_text
from src.knowledge.schemas import (
    VALID_DOMAINS,
    VALID_SCOPE_TYPES,
    KnowledgeChunkResult,
    KnowledgeIngestRequest,
)
from src.models.knowledge import KnowledgeChunk, KnowledgeDocument


class KnowledgeService:
    """知识库服务，供导入脚本和 agent 检索节点调用"""

    async def ingest(
        self,
        request: KnowledgeIngestRequest,
        db: AsyncSession,
    ) -> KnowledgeDocument | None:
        """导入一份知识库文档

        参数:
            request: 文档导入请求，包含内容、权限范围和领域标签
            db: SQLAlchemy 异步数据库会话

        返回:
            KnowledgeDocument | None: 新建文档；重复内容返回 None
        """
        self._validate_request(request)
        checksum = sha256(request.content.encode("utf-8")).hexdigest()
        existing = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.checksum == checksum)
        )
        if existing.scalar_one_or_none() is not None:
            return None

        now = datetime.now(UTC).isoformat()
        document = KnowledgeDocument(
            title=request.title,
            source=request.source,
            scope_type=request.scope_type,
            scope_id=request.scope_id,
            domain=request.domain,
            checksum=checksum,
            created_by=request.created_by,
            created_at=now,
            updated_at=now,
        )
        db.add(document)
        await db.flush()

        for chunk in chunk_text(request.content):
            db.add(
                KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    scope_type=request.scope_type,
                    scope_id=request.scope_id,
                    domain=request.domain,
                    token_count=chunk.token_count,
                    source=request.source,
                    created_at=now,
                )
            )
        await db.flush()
        return document

    async def search(
        self,
        query: str,
        user_id: str,
        db: AsyncSession,
        chat_type: str = "single",
        chat_id: str | None = None,
        domains: list[str] | None = None,
        limit: int = 5,
    ) -> list[KnowledgeChunkResult]:
        """检索当前用户或群聊可见的知识片段

        参数:
            query: 用户查询文本
            user_id: 当前用户 ID
            db: SQLAlchemy 异步数据库会话
            chat_type: 会话类型，"single" 或 "group"
            chat_id: 群聊 ID，群聊场景使用
            domains: 允许检索的领域列表
            limit: 最多返回数量

        返回:
            list[KnowledgeChunkResult]: 按简单关键词分数排序的结果
        """
        allowed_domains = domains or ["global", "qa"]
        for domain in allowed_domains:
            if domain not in VALID_DOMAINS:
                raise ValueError(f"Invalid knowledge domain: {domain}")

        scope_filter = self._build_scope_filter(user_id, chat_type, chat_id)
        result = await db.execute(
            select(KnowledgeChunk, KnowledgeDocument.title)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(scope_filter)
            .where(KnowledgeChunk.domain.in_(allowed_domains))
        )
        scored: list[tuple[float, KnowledgeChunk, str]] = []
        for chunk, title in result.all():
            score = self._score(query, chunk.content, title)
            if score > 0:
                scored.append((score, chunk, title))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            KnowledgeChunkResult(
                content=chunk.content,
                title=title,
                source=chunk.source,
                score=score,
                scope_type=chunk.scope_type,
                domain=chunk.domain,
            )
            for score, chunk, title in scored[:limit]
        ]

    def _validate_request(self, request: KnowledgeIngestRequest) -> None:
        """校验导入请求是否合法

        参数:
            request: 文档导入请求

        返回:
            None；非法时抛出 ValueError
        """
        if request.scope_type not in VALID_SCOPE_TYPES:
            raise ValueError(f"Invalid knowledge scope_type: {request.scope_type}")
        if request.domain not in VALID_DOMAINS:
            raise ValueError(f"Invalid knowledge domain: {request.domain}")
        if request.scope_type == "public" and request.scope_id is not None:
            raise ValueError("Public knowledge must not have scope_id")
        if request.scope_type in {"user", "group"} and not request.scope_id:
            raise ValueError("Private knowledge must have scope_id")

    def _build_scope_filter(self, user_id: str, chat_type: str, chat_id: str | None):
        """构造知识可见范围过滤条件

        参数:
            user_id: 当前用户 ID
            chat_type: 会话类型
            chat_id: 群聊 ID

        返回:
            SQLAlchemy 条件表达式
        """
        public_filter = KnowledgeChunk.scope_type == "public"
        if chat_type == "group":
            if not chat_id:
                return public_filter
            return or_(
                public_filter,
                and_(KnowledgeChunk.scope_type == "group", KnowledgeChunk.scope_id == chat_id),
            )
        return or_(
            public_filter,
            and_(KnowledgeChunk.scope_type == "user", KnowledgeChunk.scope_id == user_id),
        )

    def _score(self, query: str, content: str, title: str) -> float:
        """计算简单关键词匹配分数

        参数:
            query: 查询文本
            content: chunk 内容
            title: 文档标题

        返回:
            float: 匹配分数，0 表示不匹配
        """
        normalized_query = query.strip().lower()
        if not normalized_query:
            return 0.0
        haystack = f"{title}\n{content}".lower()
        if normalized_query in haystack:
            return 10.0 + haystack.count(normalized_query)

        terms = [term for term in normalized_query.replace("，", " ").replace("。", " ").split() if term]
        matched = sum(1 for term in terms if term in haystack)
        return float(matched)
```

- [ ] **Step 4: Export KnowledgeService**

Modify `src/knowledge/__init__.py`:

```python
"""知识库模块包，提供文档切块、入库和检索服务"""
from src.knowledge.schemas import (
    KnowledgeChunkInput,
    KnowledgeChunkResult,
    KnowledgeIngestRequest,
)
from src.knowledge.chunking import chunk_text
from src.knowledge.service import KnowledgeService

__all__ = [
    "KnowledgeChunkInput",
    "KnowledgeChunkResult",
    "KnowledgeIngestRequest",
    "KnowledgeService",
    "chunk_text",
]
```

- [ ] **Step 5: Run service tests and verify they pass**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_knowledge_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/knowledge/__init__.py src/knowledge/service.py tests/test_knowledge_service.py
git commit -m "feat: add scoped knowledge service"
```

## Task 4: Local Knowledge Import CLI

**Files:**
- Create: `scripts/ingest_knowledge.py`
- Test: `tests/test_knowledge_service.py`

- [ ] **Step 1: Add CLI-shaped validation test**

Append to `tests/test_knowledge_service.py`:

```python
def test_ingest_request_rejects_invalid_private_scope():
    """验证私有知识缺少 scope_id 时会被拒绝

    参数:
        无

    返回:
        None；通过断言确认非法导入请求抛出 ValueError
    """
    service = KnowledgeService()
    request = KnowledgeIngestRequest(
        title="非法资料",
        source="invalid.md",
        content="这份资料缺少用户或群聊 ID。",
        scope_type="user",
        scope_id=None,
        domain="qa",
        created_by="user_a",
    )

    import pytest

    with pytest.raises(ValueError, match="Private knowledge must have scope_id"):
        service._validate_request(request)
```

- [ ] **Step 2: Run validation test and verify it passes**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_knowledge_service.py::test_ingest_request_rejects_invalid_private_scope -q
```

Expected: PASS because Task 3 already added validation.

- [ ] **Step 3: Create local CLI script**

Create `scripts/ingest_knowledge.py`:

```python
"""
本地知识库导入脚本
从本地 .md/.txt 文件读取内容，并通过 KnowledgeService 写入 SQLite

Workflow:
  命令行参数 → 读取文件 → 创建 KnowledgeIngestRequest → KnowledgeService.ingest()
"""
import argparse
import asyncio
from pathlib import Path

from src.db.session import AsyncSessionLocal
from src.knowledge.schemas import KnowledgeIngestRequest
from src.knowledge.service import KnowledgeService


def parse_args() -> argparse.Namespace:
    """解析命令行参数

    参数:
        无

    返回:
        argparse.Namespace: 包含文件路径、scope、domain 等导入参数
    """
    parser = argparse.ArgumentParser(description="Import a Markdown/TXT document into the knowledge base.")
    parser.add_argument("path", help="Path to .md or .txt document")
    parser.add_argument("--title", default="", help="Document title; defaults to filename")
    parser.add_argument("--scope-type", required=True, choices=["public", "user", "group"])
    parser.add_argument("--scope-id", default=None, help="Required for user/group scopes")
    parser.add_argument("--domain", required=True, choices=["global", "qa", "fitness", "meal", "summary"])
    parser.add_argument("--created-by", default=None, help="Creator user_id")
    return parser.parse_args()


async def main() -> None:
    """执行文档导入

    参数:
        无

    返回:
        None；导入结果打印到标准输出
    """
    args = parse_args()
    path = Path(args.path)
    if path.suffix.lower() not in {".md", ".txt"}:
        raise SystemExit("Only .md and .txt files are supported in Stage 1")
    content = path.read_text(encoding="utf-8")
    request = KnowledgeIngestRequest(
        title=args.title or path.stem,
        source=str(path),
        content=content,
        scope_type=args.scope_type,
        scope_id=args.scope_id,
        domain=args.domain,
        created_by=args.created_by,
    )
    service = KnowledgeService()
    async with AsyncSessionLocal() as db:
        document = await service.ingest(request, db)
        await db.commit()
    if document is None:
        print("Skipped duplicate document")
    else:
        print(f"Imported document #{document.id}: {document.title}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run CLI help**

Run:

```bash
DEEPSEEK_API_KEY=test uv run python scripts/ingest_knowledge.py --help
```

Expected: command prints usage text containing `--scope-type`, `--scope-id`, and `--domain`.

- [ ] **Step 5: Run knowledge tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_knowledge_service.py tests/test_knowledge_chunking.py tests/test_knowledge_model.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add scripts/ingest_knowledge.py tests/test_knowledge_service.py
git commit -m "feat: add local knowledge import CLI"
```

## Task 5: QAAgent RAG Integration

**Files:**
- Modify: `src/agents/registry.py`
- Modify: `src/agents/base.py`
- Modify: `src/agents/qa/state.py`
- Modify: `src/agents/qa/nodes.py`
- Modify: `src/agents/qa/graph.py`
- Modify: `src/router/debug.py`
- Modify: `src/wechat/router.py`
- Modify: `src/wechat/robot_router.py`
- Test: `tests/test_qa.py`

- [ ] **Step 1: Add QA RAG tests**

Append to `tests/test_qa.py`:

```python
import pytest

from src.agents.qa.graph import QAAgent
from src.knowledge.schemas import KnowledgeIngestRequest
from src.knowledge.service import KnowledgeService


@pytest.mark.asyncio
async def test_qa_agent_injects_knowledge_context(mock_llm, db_session):
    """验证 QAAgent 会把知识库片段注入 LLM prompt

    参数:
        mock_llm: 模拟 LLM 客户端
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 LLM system prompt 包含知识库资料
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="小管家资料",
            source="qa.md",
            content="小管家回答知识库问题时必须优先使用资料。",
            scope_type="public",
            scope_id=None,
            domain="qa",
            created_by="admin",
        ),
        db_session,
    )
    mock_llm.chat.return_value = "我会优先参考资料。"
    agent = QAAgent(mock_llm)

    result = await agent.handle("qa", "小管家回答知识库问题时应该怎么做？", "user_a", db_session)

    assert result.reply == "我会优先参考资料。"
    messages = mock_llm.chat.call_args.kwargs["messages"]
    system_prompt = messages[0]["content"]
    assert "以下是可参考的知识库资料" in system_prompt
    assert "小管家资料" in system_prompt
    assert "必须优先使用资料" in system_prompt


@pytest.mark.asyncio
async def test_qa_agent_uses_group_scope_when_extra_state_is_group(mock_llm, db_session):
    """验证 QAAgent 在群聊状态下检索群聊私有知识

    参数:
        mock_llm: 模拟 LLM 客户端
        db_session: 测试数据库会话

    返回:
        None；通过断言确认群聊资料进入 LLM prompt
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="群聊项目资料",
            source="group.md",
            content="群聊项目代号是青松。",
            scope_type="group",
            scope_id="chat_a",
            domain="qa",
            created_by="user_a",
        ),
        db_session,
    )
    mock_llm.chat.return_value = "项目代号是青松。"
    agent = QAAgent(mock_llm)

    await agent.handle(
        "qa",
        "项目代号是什么？",
        "user_a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat_a"},
    )

    messages = mock_llm.chat.call_args.kwargs["messages"]
    assert "群聊项目代号是青松" in messages[0]["content"]


@pytest.mark.asyncio
async def test_qa_agent_continues_when_knowledge_search_has_no_result(mock_llm, db_session):
    """验证知识库无命中时 QAAgent 仍然正常回复

    参数:
        mock_llm: 模拟 LLM 客户端
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 QA 回复不依赖知识命中
    """
    mock_llm.chat.return_value = "我暂时没有资料，但可以先给你一个保守回答。"
    agent = QAAgent(mock_llm)

    result = await agent.handle("qa", "一个没有资料的问题", "user_a", db_session)

    assert result.reply == "我暂时没有资料，但可以先给你一个保守回答。"
```

- [ ] **Step 2: Run QA RAG tests and verify they fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_qa.py::test_qa_agent_injects_knowledge_context tests/test_qa.py::test_qa_agent_uses_group_scope_when_extra_state_is_group tests/test_qa.py::test_qa_agent_continues_when_knowledge_search_has_no_result -q
```

Expected: FAIL because QAAgent does not retrieve knowledge or accept `extra_state`.

- [ ] **Step 3: Update agent protocol**

Modify `src/agents/registry.py` method signature:

```python
    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识
            message: 用户消息
            user_id: 用户标识
            db: 数据库会话
            extra_state: 可选，路由层传入的额外上下文字段

        返回:
            AgentResponse: 处理结果
        """
        ...
```

Modify `src/agents/base.py` abstract method signature:

```python
    @abstractmethod
    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理用户消息，执行对应业务逻辑

        参数:
            intent: 意图分类结果（如 log_training / qa / today_plan 等）
            message: 用户原始消息文本
            user_id: 用户唯一标识（企业微信 OpenID 或调试用户 ID）
            db: SQLAlchemy 异步数据库会话，用于读写训练记录和用户偏好
            extra_state: 可选，路由层传入的 chat_type/chat_id 等额外上下文

        返回:
            AgentResponse: 包含回复文本和可选结构化数据的响应对象
        """
        ...
```

- [ ] **Step 4: Update QA state**

Modify `src/agents/qa/state.py` by adding these fields to `QAState`:

```python
    chat_type: str
    """会话类型："single" 或 "group"，用于知识库 scope 过滤"""

    chat_id: Optional[str]
    """群聊 ID，群聊知识库检索时使用"""

    knowledge_context: list[dict]
    """知识库检索结果列表，用于注入 LLM prompt"""

    knowledge_error: Optional[str]
    """知识库检索错误信息；存在时不阻断 QA 回复"""
```

- [ ] **Step 5: Add retrieve_knowledge node and prompt formatting**

Modify `src/agents/qa/nodes.py` imports:

```python
import json
from sqlalchemy import select
from langgraph.config import get_config
from src.models.preference import UserPreference, DEFAULT_PREFERENCES
from src.knowledge.service import KnowledgeService
```

Modify `QA_SYSTEM_PROMPT` to include `{knowledge_context}` before `{conversation_context}`:

```python
QA_SYSTEM_PROMPT = """你是"小管家"，用户的私人 AI 助理，陪伴用户日常生活。

性格底色：细心、温暖、偶尔带点小幽默但不油腻。

说话方式：
- 像认识很久的朋友，自然口语化，不要客服腔和机器人感
- 用户偏好中有名字的话，偶尔叫名字显得亲近
- 关心用户的感受和状态，不只是一问一答
- 适当用 emoji 传递情绪，不泛滥
- 不知道就说不知道，不要编

回复长度：日常聊天 2-4 句即可，深入问题可以详细展开。

用户档案（来自系统记录）：
{preferences}

{knowledge_context}

{conversation_context}"""
```

Add helper and node below `fetch_preferences`:

```python
def _format_knowledge_context(items: list[dict]) -> str:
    """格式化知识库检索结果为 prompt 文本

    参数:
        items: 知识库检索结果字典列表

    返回:
        str: 可直接注入 system prompt 的知识库上下文
    """
    if not items:
        return "（暂无可参考的知识库资料）"
    blocks = ["以下是可参考的知识库资料。优先使用这些资料回答；资料不足时要明确说不知道，不要编造。"]
    for index, item in enumerate(items, start=1):
        blocks.append(
            f"[{index}] {item['title']} - {item['source']}\n{item['content']}"
        )
    return "\n\n".join(blocks)


async def retrieve_knowledge(state: dict) -> dict:
    """检索 QA 可用的知识库资料

    参数:
        state: 包含 message、user_id、chat_type、chat_id 的当前状态

    返回:
        dict: {"knowledge_context": [...]} 或 {"knowledge_error": "...", "knowledge_context": []}
    """
    db = get_config()["configurable"]["db"]
    service = KnowledgeService()
    try:
        results = await service.search(
            query=state["message"],
            user_id=state["user_id"],
            db=db,
            chat_type=state.get("chat_type", "single"),
            chat_id=state.get("chat_id"),
            domains=["global", "qa"],
            limit=5,
        )
        return {
            "knowledge_context": [
                {
                    "content": item.content,
                    "title": item.title,
                    "source": item.source,
                    "score": item.score,
                    "scope_type": item.scope_type,
                    "domain": item.domain,
                }
                for item in results
            ]
        }
    except Exception as e:
        return {"knowledge_error": str(e), "knowledge_context": []}
```

Modify `generate_qa_response` system prompt formatting:

```python
                "content": QA_SYSTEM_PROMPT.format(
                    preferences=json.dumps(state.get("preferences", {}), ensure_ascii=False),
                    knowledge_context=_format_knowledge_context(state.get("knowledge_context", [])),
                    conversation_context=conversation_context,
                ),
```

- [ ] **Step 6: Update QA graph**

Modify imports in `src/agents/qa/graph.py`:

```python
from src.agents.qa.nodes import (
    fetch_preferences,
    retrieve_knowledge,
    generate_qa_response,
    format_qa_response,
)
```

Modify graph assembly:

```python
        builder.add_node("fetch_prefs", fetch_preferences)
        builder.add_node("retrieve_knowledge", retrieve_knowledge)
        builder.add_node("generate", generate_qa_response)
        builder.add_node("format", format_qa_response)

        builder.set_entry_point("fetch_prefs")
        builder.add_edge("fetch_prefs", "retrieve_knowledge")
        builder.add_edge("retrieve_knowledge", "generate")
        builder.add_edge("generate", "format")
        builder.add_edge("format", END)
```

Modify `QAAgent.handle()` signature and initial state:

```python
    async def handle(
        self,
        intent: str,
        message: str,
        user_id: str,
        db,
        extra_state: dict | None = None,
    ) -> AgentResponse:
        """处理用户消息的入口方法

        参数:
            intent: 意图标识（"qa" 或 "unknown"）
            message: 用户原始消息文本
            user_id: 用户唯一标识
            db: SQLAlchemy 异步数据库会话
            extra_state: 可选，路由层传入的 chat_type/chat_id 等额外上下文

        返回:
            AgentResponse: 包含个性化回复文本的响应
        """
        memory = ConversationMemory(self._llm)
        summary, recent = await memory.get_context(user_id, db)

        initial_state: dict = {
            "intent": intent,
            "message": message,
            "user_id": user_id,
            "conversation_summary": summary,
            "recent_messages": recent,
            "chat_type": "single",
            "chat_id": None,
        }
        if extra_state:
            initial_state.update(extra_state)
        config = {"configurable": {"db": db, "llm": self._llm, "thread_id": user_id}}
        result = await self._graph.ainvoke(initial_state, config)

        reply = result.get("reply", "")
        await memory.save_exchange(user_id, message, reply, db)
        return AgentResponse(reply=reply, data=result.get("data"))
```

- [ ] **Step 7: Pass chat metadata from debug route**

In `src/router/debug.py`, modify the private agent call:

```python
            result = await agent.handle(
                intent,
                req.message,
                req.user_id,
                db,
                extra_state={"chat_type": req.chat_type, "chat_id": req.chat_id or None},
            )
```

Keep the existing `summarize_group` call unchanged because it already passes `extra_state`.

- [ ] **Step 8: Pass chat metadata from WeChat routers**

In `src/wechat/router.py`, replace the non-summary call:

```python
                        result = await agent.handle(intent, content, from_user, db)
```

with:

```python
                        result = await agent.handle(
                            intent,
                            content,
                            from_user,
                            db,
                            extra_state={"chat_type": chat_type, "chat_id": chat_id or None},
                        )
```

In `src/wechat/robot_router.py`, replace the non-summary call:

```python
                        result = await agent.handle(intent, content, from_user, db)
```

with:

```python
                        result = await agent.handle(
                            intent,
                            content,
                            from_user,
                            db,
                            extra_state={"chat_type": chat_type, "chat_id": chat_id or None},
                        )
```

Keep existing `summarize_group` calls unchanged because both routers already pass `extra_state={"chat_id": chat_id, "chat_type": "group"}` there.

- [ ] **Step 9: Run QA tests and verify they pass**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_qa.py tests/test_knowledge_service.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit Task 5**

```bash
git add src/agents/registry.py src/agents/base.py src/agents/qa/state.py src/agents/qa/nodes.py src/agents/qa/graph.py src/router/debug.py src/wechat/router.py src/wechat/robot_router.py tests/test_qa.py
git commit -m "feat: connect QA agent to knowledge retrieval"
```

## Task 6: Documentation and Full Verification

**Files:**
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/upgrade-roadmap.md`

- [ ] **Step 1: Update active context**

Modify `docs/agent/active-context.md` by adding this bullet to `What Is Implemented`:

```markdown
- Stage 1 knowledge-base RAG: SQLite-backed public/user/group scoped knowledge documents and chunks, local `.md`/`.txt` import CLI, scoped retrieval service, and QAAgent knowledge-context injection.
```

Modify `Deferred Work` so `RAG or knowledge-base integration` becomes:

```markdown
- RAG Stage 2/3: hybrid vector retrieval, PDF/web imports, file upload UI, index rebuild operations, and broader Fitness/Meal/Summary integration.
```

- [ ] **Step 2: Update implementation patterns**

Append to `docs/agent/patterns.md`:

```markdown
## Knowledge Base Pattern

Knowledge retrieval is centralized in `src/knowledge/service.py`.

- Agents must call `KnowledgeService.search()` instead of querying `knowledge_chunks` directly.
- `search()` owns scope filtering: private chat can see `public + user`, group chat can see `public + group`.
- Group chat does not read the speaker's user-private knowledge unless a future explicit opt-in is added.
- Agents pass domain allowlists such as `["global", "qa"]`; they do not hard-code SQL filters.
- `KnowledgeService.ingest()` owns validation, checksum deduplication, chunking, and ORM writes.
- Stage 1 imports use `scripts/ingest_knowledge.py` for local `.md` / `.txt` files.
```

- [ ] **Step 3: Update roadmap**

Modify `docs/agent/upgrade-roadmap.md` section `4.1 知识库集成` to:

```markdown
### 4.1 知识库集成

- **当前**: Stage 1 已支持 SQLite 知识库、public/user/group scope 隔离、QAAgent RAG 注入、本地 `.md`/`.txt` 导入脚本。
- **下一步**: 接入混合检索（FTS + embedding）、PDF/网页导入、文件上传 UI，并逐步扩展到 FitnessAgent 和 MealAgent。
- **收益**: 回答更专业、更个性化，减少 LLM 幻觉，同时保留多用户/多群聊知识隔离。
- **剩余工作量**: 中到大（主要取决于向量数据库、文件管理和后台索引重建需求）。
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_knowledge_model.py tests/test_knowledge_chunking.py tests/test_knowledge_service.py tests/test_qa.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: PASS.

- [ ] **Step 6: Scan for root doc sync needs**

Run:

```bash
cmp -s AGENTS.md CLAUDE.md && echo "root docs identical"
```

Expected: prints `root docs identical`.

This plan does not require editing `AGENTS.md` or `CLAUDE.md`. If a later implementation changes either file, copy the changed root entry file to the other one before final verification.

- [ ] **Step 7: Commit Task 6**

```bash
git add docs/agent/active-context.md docs/agent/patterns.md docs/agent/upgrade-roadmap.md
git commit -m "docs: document knowledge base pattern"
```

## Self-Review

- Spec coverage: Stage 1 includes models, chunking, service, scope filtering, domain filtering, local `.md`/`.txt` import, QAAgent integration, permission tests, and documentation. Stage 2/3 items from the spec are intentionally documented as future work in the design and roadmap.
- Placeholder scan: The plan uses concrete file paths, commands, expected outputs, and code snippets for every code-changing step.
- Type consistency: `scope_type`, `scope_id`, `domain`, `chat_type`, `chat_id`, `knowledge_context`, and `knowledge_error` are named consistently across schemas, models, service, state, and QA nodes.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-02-rag-knowledge-base-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
