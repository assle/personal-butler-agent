"""
知识库服务
封装文档入库和检索逻辑，集中处理 scope/domain 权限过滤

Workflow:
  ingest() 校验请求 → 切块 → 写入 KnowledgeDocument/KnowledgeChunk → 写入 FTS 和向量索引
  search() 构造可见范围 → FTS/关键词/向量混合召回 → 合并评分 → 返回 KnowledgeChunkResult
"""
import json
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.knowledge.chunking import chunk_text
from src.knowledge.embedding import EmbeddingService
from src.knowledge.schemas import (
    VALID_DOMAINS,
    VALID_SCOPE_TYPES,
    KnowledgeChunkResult,
    KnowledgeIngestRequest,
)
from src.models.knowledge import (
    KnowledgeChunk,
    KnowledgeChunkEmbedding,
    KnowledgeDocument,
)


class KnowledgeService:
    """知识库服务，供导入脚本和 agent 检索节点调用"""

    def __init__(self, embedding_service: EmbeddingService | None = None):
        """初始化知识库服务

        参数:
            embedding_service: 可选嵌入服务；默认使用本地哈希嵌入

        返回:
            None
        """
        self.embedding_service = embedding_service or EmbeddingService()

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

        await self._ensure_fts_table(db)

        for chunk_input in chunk_text(request.content):
            chunk = KnowledgeChunk(
                document_id=document.id,
                chunk_index=chunk_input.chunk_index,
                content=chunk_input.content,
                scope_type=request.scope_type,
                scope_id=request.scope_id,
                domain=request.domain,
                token_count=chunk_input.token_count,
                source=request.source,
                created_at=now,
            )
            db.add(chunk)
            await db.flush()

            await self._index_fts_chunk(db, chunk, document.title)
            db.add(
                KnowledgeChunkEmbedding(
                    chunk_id=chunk.id,
                    model_name=self.embedding_service.model_name,
                    dimension=self.embedding_service.dimension,
                    vector_json=json.dumps(
                        self.embedding_service.embed(
                            f"{document.title}\n{chunk.content}"
                        )
                    ),
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

        await self._ensure_fts_table(db)
        scope_filter = self._build_scope_filter(user_id, chat_type, chat_id)
        result = await db.execute(
            select(KnowledgeChunk, KnowledgeDocument.title, KnowledgeChunkEmbedding.vector_json)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .outerjoin(
                KnowledgeChunkEmbedding,
                and_(
                    KnowledgeChunkEmbedding.chunk_id == KnowledgeChunk.id,
                    KnowledgeChunkEmbedding.model_name == self.embedding_service.model_name,
                ),
            )
            .where(scope_filter)
            .where(KnowledgeChunk.domain.in_(allowed_domains))
        )
        fts_scores = await self._search_fts(db, query)
        query_vector = self.embedding_service.embed(query)

        scored: list[tuple[float, KnowledgeChunk, str]] = []
        for chunk, title, vector_json in result.all():
            lexical_score = self._score(query, chunk.content, title)
            fts_score = fts_scores.get(chunk.id, 0.0)
            vector_score = self._vector_score(
                query_vector,
                vector_json,
                fallback_text=f"{title}\n{chunk.content}",
            )
            score = self._hybrid_score(lexical_score, fts_score, vector_score)
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

    async def _ensure_fts_table(self, db: AsyncSession) -> None:
        """确保 SQLite FTS5 索引表存在

        参数:
            db: SQLAlchemy 异步数据库会话

        返回:
            None；缺失时创建 knowledge_chunks_fts 虚拟表
        """
        await db.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
                USING fts5(title, source, content, tokenize='unicode61')
                """
            )
        )

    async def _index_fts_chunk(
        self,
        db: AsyncSession,
        chunk: KnowledgeChunk,
        title: str,
    ) -> None:
        """将 chunk 写入 SQLite FTS 索引

        参数:
            db: SQLAlchemy 异步数据库会话
            chunk: 已 flush 且拥有 id 的知识库 chunk
            title: chunk 所属文档标题

        返回:
            None
        """
        await db.execute(
            text(
                """
                INSERT OR REPLACE INTO knowledge_chunks_fts(rowid, title, source, content)
                VALUES (:rowid, :title, :source, :content)
                """
            ),
            {
                "rowid": chunk.id,
                "title": title,
                "source": chunk.source,
                "content": chunk.content,
            },
        )

    async def _search_fts(self, db: AsyncSession, query: str) -> dict[int, float]:
        """使用 SQLite FTS 查询候选 chunk 分数

        参数:
            db: SQLAlchemy 异步数据库会话
            query: 用户查询文本

        返回:
            dict[int, float]: chunk_id 到 FTS 分数的映射
        """
        fts_query = self._fts_query(query)
        if not fts_query:
            return {}
        try:
            result = await db.execute(
                text(
                    """
                    SELECT rowid, bm25(knowledge_chunks_fts) AS rank
                    FROM knowledge_chunks_fts
                    WHERE knowledge_chunks_fts MATCH :query
                    ORDER BY rank
                    LIMIT 50
                    """
                ),
                {"query": fts_query},
            )
        except Exception:
            return {}

        scores: dict[int, float] = {}
        for rowid, rank in result.all():
            scores[int(rowid)] = 1.0 / (1.0 + abs(float(rank)))
        return scores

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

        terms = [
            term
            for term in normalized_query.replace("，", " ").replace("。", " ").split()
            if term
        ]
        matched = sum(1 for term in terms if term in haystack)
        if matched > 0:
            return float(matched)

        compact_query = "".join(
            char for char in normalized_query if char.isalnum() or "\u4e00" <= char <= "\u9fff"
        )
        bigrams = {
            compact_query[index:index + 2]
            for index in range(max(0, len(compact_query) - 1))
        }
        bigram_matches = sum(1 for bigram in bigrams if bigram in haystack)
        return float(bigram_matches) / 10.0

    def _fts_query(self, query: str) -> str:
        """生成安全的 FTS MATCH 查询

        参数:
            query: 用户查询文本

        返回:
            str: 用 OR 连接的 FTS token 查询；无可用 token 时返回空字符串
        """
        normalized = query.strip().lower()
        if not normalized:
            return ""
        terms = [
            term
            for term in normalized.replace("，", " ").replace("。", " ").split()
            if term and all(char.isalnum() or "\u4e00" <= char <= "\u9fff" for char in term)
        ]
        if terms:
            return " OR ".join(terms[:8])

        compact = "".join(
            char for char in normalized if char.isalnum() or "\u4e00" <= char <= "\u9fff"
        )
        return compact[:64]

    def _vector_score(
        self,
        query_vector: list[float],
        vector_json: str | None,
        fallback_text: str = "",
    ) -> float:
        """计算查询向量与 chunk 向量的相似度

        参数:
            query_vector: 用户查询的本地嵌入向量
            vector_json: 数据库保存的 chunk 向量 JSON
            fallback_text: 缺少已保存向量时用于即时嵌入的文本

        返回:
            float: 向量相似度；缺失或解析失败时返回 0
        """
        if not vector_json:
            if not fallback_text:
                return 0.0
            return self.embedding_service.similarity(
                query_vector,
                self.embedding_service.embed(fallback_text),
            )
        try:
            chunk_vector = json.loads(vector_json)
        except json.JSONDecodeError:
            return 0.0
        return self.embedding_service.similarity(query_vector, chunk_vector)

    def _hybrid_score(
        self,
        lexical_score: float,
        fts_score: float,
        vector_score: float,
    ) -> float:
        """合并关键词、FTS 和向量分数

        参数:
            lexical_score: 现有关键词和字符 bigram 分数
            fts_score: SQLite FTS bm25 转换后的分数
            vector_score: 本地 embedding 相似度

        返回:
            float: 统一排序分数
        """
        normalized_lexical = min(1.0, lexical_score / 10.0)
        return normalized_lexical * 0.45 + fts_score * 0.25 + vector_score * 0.30
