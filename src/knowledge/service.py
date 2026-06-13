"""
知识库服务
封装 Chroma 向量存储 + SQLite FTS + 关键词检索，支持多格式导入和两阶段检索。

Workflow:
  ingest() 解析文档 → 写入 SQLite chunks → 批量写入 Chroma
  search() 查询重写 → 多路粗筛 → LLM 精排 → 返回结果
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge.chroma_store import ChromaStore
from src.knowledge.chunking import chunk_text
from src.knowledge.embedding import EmbeddingService
from src.knowledge.keyword_search import KeywordSearchBackend
from src.knowledge.reranker import rerank_chunks, rewrite_query
from src.knowledge.schemas import (
    VALID_DOMAINS,
    VALID_SCOPE_TYPES,
    KnowledgeChunkResult,
    KnowledgeIngestRequest,
)
from src.models.knowledge import KnowledgeDocument, KnowledgeChunk

logger = logging.getLogger(__name__)


class KnowledgeService:
    """知识库服务，供导入脚本和 agent 检索节点调用"""

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        chroma_store: ChromaStore | None = None,
        keyword_search: KeywordSearchBackend | None = None,
    ):
        """初始化知识库服务

        参数:
            embedding_service: 嵌入服务
            chroma_store: Chroma 向量存储；不传则不启用 Chroma（向后兼容）
            keyword_search: 关键词检索后端；不传则默认创建 KeywordSearchBackend

        返回:
            None
        """
        self._embedding = embedding_service or EmbeddingService()
        self._chroma = chroma_store
        self._keyword_backend = keyword_search or KeywordSearchBackend()

    # ── 导入 ──────────────────────────────────────────

    async def ingest(
        self,
        request: KnowledgeIngestRequest,
        db: AsyncSession,
    ) -> KnowledgeDocument | None:
        """导入一份知识库文档

        参数:
            request: 文档导入请求
            db: SQLAlchemy 异步数据库会话

        返回:
            KnowledgeDocument | None: 新建文档；重复返回 None
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

        await self._ensure_keyword_index(db)

        chunks_input = chunk_text(request.content)
        chroma_payloads: list[dict] = []
        chroma_texts: list[str] = []

        for ci in chunks_input:
            chunk = KnowledgeChunk(
                document_id=document.id,
                chunk_index=ci.chunk_index,
                content=ci.content,
                scope_type=request.scope_type,
                scope_id=request.scope_id,
                domain=request.domain,
                token_count=ci.token_count,
                source=request.source,
                created_at=now,
            )
            db.add(chunk)
            await db.flush()

            await self._keyword_backend.index_chunk(
                db, self._dialect_name(db), chunk, document.title
            )

            chroma_payloads.append({
                "chunk_id": chunk.id,
                "document_id": document.id,
                "title": document.title,
                "source": request.source,
                "scope_type": request.scope_type,
                "scope_id": request.scope_id,
                "domain": request.domain,
                "chunk_index": ci.chunk_index,
                "content": ci.content,
            })
            chroma_texts.append(f"{document.title}\n{ci.content}")

        # 批量嵌入并写入 Chroma
        if self._chroma is not None and chroma_payloads:
            embeddings = await self._embedding.batch_embed(chroma_texts)
            self._chroma.index_chunks(chroma_payloads, embeddings)

        await db.flush()
        logger.info("Knowledge: ingested document #%d (%d chunks)", document.id, len(chunks_input))
        return document

    # ── 检索 ──────────────────────────────────────────

    async def search(
        self,
        query: str,
        user_id: str,
        db: AsyncSession,
        chat_type: str = "single",
        chat_id: str | None = None,
        domains: list[str] | None = None,
        limit: int = 5,
        llm=None,
    ) -> list[KnowledgeChunkResult]:
        """两阶段检索：查询重写 → 多路粗筛 → LLM 精排

        参数:
            query: 用户查询
            user_id: 用户 ID
            db: SQLAlchemy 会话
            chat_type: "single" / "group"
            chat_id: 群 ID
            domains: 领域标签
            limit: 返回条数
            llm: LLMClient（用于 query rewriting 和 re-ranking）

        返回:
            list[KnowledgeChunkResult]
        """
        allowed_domains = domains or ["global", "qa"]
        for domain in allowed_domains:
            if domain not in VALID_DOMAINS:
                raise ValueError(f"Invalid knowledge domain: {domain}")

        await self._ensure_keyword_index(db)
        scope_filter = self._build_scope_filter(user_id, chat_type, chat_id)

        # Step 1: Query Rewriting
        queries = [query]
        if llm is not None:
            queries = await rewrite_query(query, llm)

        # Step 2: 多路粗筛
        seen_ids: set[int] = set()
        candidates: list[dict] = []

        for q in queries:
            for chunk_dict in await self._coarse_retrieval(
                q, db, scope_filter, allowed_domains, chat_type, chat_id
            ):
                cid = chunk_dict.get("chunk_id", 0)
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    candidates.append(chunk_dict)

        if not candidates:
            logger.info(
                "Knowledge search: query='%.60s' user=%s type=%s → 0 results",
                query, user_id, chat_type,
            )
            return []

        # Step 3: LLM Re-rank
        if llm is not None and len(candidates) > limit:
            candidates = await rerank_chunks(query, candidates, llm, top_k=limit)
        else:
            candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
            candidates = candidates[:limit]

        results = [
            KnowledgeChunkResult(
                content=c["content"],
                title=c.get("title", ""),
                source=c.get("source", ""),
                score=c.get("relevance_score", c.get("score", 0.0)),
                scope_type=c.get("scope_type", ""),
                domain=c.get("domain", ""),
            )
            for c in candidates
        ]
        sources = ", ".join(
            f"{r.title}({r.score:.2f})" for r in results
        )
        logger.info(
            "Knowledge search: query='%.60s' user=%s type=%s → %d results (from %d coarse) sources=[%s] chroma=%s",
            query, user_id, chat_type, len(results), len(candidates), sources,
            self._chroma is not None,
        )
        return results

    async def search_research(
        self,
        query: str,
        access_scope,
        db: AsyncSession,
        domains: list[str] | None = None,
        limit: int = 5,
        llm=None,
    ) -> list[KnowledgeChunkResult]:
        """按研究任务不可变权限范围检索

        参数:
            query: 检索查询
            access_scope: ResearchAccessScope 实例
            db: 异步数据库会话
            domains: 领域标签
            limit: 返回条数
            llm: LLMClient

        返回:
            list[KnowledgeChunkResult]
        """
        return await self.search(
            query=query,
            user_id=access_scope.user_id,
            db=db,
            chat_type="single",
            domains=domains or ["global", "qa"],
            limit=limit,
            llm=llm,
        )

    async def _coarse_retrieval(
        self,
        query: str,
        db: AsyncSession,
        scope_filter,
        allowed_domains: list[str],
        chat_type: str,
        chat_id: str | None,
    ) -> list[dict]:
        """多路粗筛：FTS + Chroma 向量，合并去重

        参数:
            query: 单个查询文本
            db: 数据库会话
            scope_filter: SQLAlchemy scope 过滤条件
            allowed_domains: 领域列表
            chat_type: 会话类型
            chat_id: 群 ID

        返回:
            list[dict]: 去重后的候选 chunk
        """
        results: list[dict] = []

        # 路 1: Chroma 向量检索
        if self._chroma is not None:
            try:
                query_vec = await self._embedding.embed(query)
                chroma_results = self._chroma.query(
                    query_vec, chat_type, chat_id, allowed_domains, n_results=20
                )
                results.extend(chroma_results)
            except Exception:
                logger.debug("Knowledge: Chroma query failed", exc_info=True)

        # 路 2: 关键词全文检索（SQLite FTS5 或 PostgreSQL tsvector）
        fts_scores = await self._keyword_backend.search(
            db, self._dialect_name(db), query, limit=20
        )
        if fts_scores:
            result = await db.execute(
                select(KnowledgeChunk, KnowledgeDocument.title)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                .where(scope_filter)
                .where(KnowledgeChunk.domain.in_(allowed_domains))
            )
            for chunk, title in result.all():
                if chunk.id in fts_scores:
                    results.append({
                        "chunk_id": chunk.id,
                        "document_id": chunk.document_id,
                        "title": title,
                        "source": chunk.source,
                        "content": chunk.content,
                        "score": float(fts_scores[chunk.id]),
                        "scope_type": chunk.scope_type,
                        "domain": chunk.domain,
                    })

        # 路 3: 关键词匹配（精确子串）
        keyword_results = await self._keyword_search(
            query, db, scope_filter, allowed_domains
        )
        results.extend(keyword_results)

        return results

    async def _keyword_search(
        self,
        query: str,
        db: AsyncSession,
        scope_filter,
        allowed_domains: list[str],
    ) -> list[dict]:
        """关键词精确匹配检索

        参数:
            query: 查询文本
            db: 数据库会话
            scope_filter: 权限过滤
            allowed_domains: 领域标签

        返回:
            list[dict]: 关键词匹配结果
        """
        normalized_query = query.strip().lower()
        if not normalized_query:
            return []

        result = await db.execute(
            select(KnowledgeChunk, KnowledgeDocument.title)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(scope_filter)
            .where(KnowledgeChunk.domain.in_(allowed_domains))
        )
        scored = []
        for chunk, title in result.all():
            haystack = f"{title}\n{chunk.content}".lower()
            if normalized_query in haystack:
                score = 10.0 + haystack.count(normalized_query)
            else:
                terms = [t for t in normalized_query.split() if t]
                matched = sum(1 for t in terms if t in haystack)
                score = float(matched) if matched > 0 else 0.0
            if score > 0:
                scored.append({
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "title": title,
                    "source": chunk.source,
                    "content": chunk.content,
                    "score": score,
                    "scope_type": chunk.scope_type,
                    "domain": chunk.domain,
                })
        return scored

    # ── 校验 ──────────────────────────────────────────

    def _validate_request(self, request: KnowledgeIngestRequest) -> None:
        """校验导入请求

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

    # ── 权限过滤 ──────────────────────────────────────

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
                and_(
                    KnowledgeChunk.scope_type == "group",
                    KnowledgeChunk.scope_id == chat_id,
                ),
            )
        return or_(
            public_filter,
            and_(KnowledgeChunk.scope_type == "user", KnowledgeChunk.scope_id == user_id),
        )

    # ── 关键词索引 ─────────────────────────────────────

    @staticmethod
    def _dialect_name(db: AsyncSession) -> str:
        """获取当前数据库方言名称

        参数:
            db: 异步数据库会话

        返回:
            str: 数据库方言名称（如 sqlite、postgresql）
        """
        return db.get_bind().dialect.name

    async def _ensure_keyword_index(self, db: AsyncSession) -> None:
        """确保关键词索引结构存在

        SQLite 创建 FTS5 虚拟表；PostgreSQL 创建 GIN 表达式索引。

        参数:
            db: 异步数据库会话

        返回:
            None
        """
        dialect = self._dialect_name(db)
        if dialect == "sqlite":
            await db.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
                    USING fts5(title, source, content, tokenize='unicode61')
                    """
                )
            )
        elif dialect == "postgresql":
            await db.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_fts_gin
                    ON knowledge_chunks
                    USING gin (
                      to_tsvector(
                        'simple',
                        coalesce(title, '') || ' ' || coalesce(content, '') || ' ' || coalesce(source, '')
                      )
                    )
                    """
                )
            )
