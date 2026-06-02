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
