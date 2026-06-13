"""
知识关键词检索后端
根据数据库方言选择 SQLite FTS5 或 PostgreSQL tsvector 实现

Workflow:
  KnowledgeService.__init__ 创建 KeywordSearchBackend 实例
  → strategy_for(dialect) 按数据库方言返回检索策略标识
  → index_chunk() / search() 按方言执行对应的写入和查询
"""
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.knowledge import KnowledgeChunk

logger = logging.getLogger(__name__)


class UnsupportedKnowledgeDialectError(RuntimeError):
    """数据库方言不支持知识关键词检索"""


class KeywordSearchBackend:
    """按数据库方言执行知识关键词检索"""

    def strategy_for(self, dialect_name: str) -> str:
        """返回数据库对应的检索策略

        参数:
            dialect_name: SQLAlchemy 数据库方言名称

        返回:
            str: sqlite_fts5 或 postgres_tsvector
        """
        if dialect_name == "sqlite":
            return "sqlite_fts5"
        if dialect_name == "postgresql":
            return "postgres_tsvector"
        raise UnsupportedKnowledgeDialectError(dialect_name)

    async def index_chunk(
        self,
        db: AsyncSession,
        dialect_name: str,
        chunk: KnowledgeChunk,
        title: str,
    ) -> None:
        """维护需要显式写入的关键词索引

        参数:
            db: 异步数据库会话
            dialect_name: 数据库方言名称
            chunk: 已持久化知识片段
            title: 文档标题

        返回:
            None
        """
        if dialect_name == "sqlite":
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
        # PostgreSQL: no-op — 索引是表达式索引，自动维护

    async def search(
        self,
        db: AsyncSession,
        dialect_name: str,
        query: str,
        *,
        limit: int = 20,
    ) -> dict[int, float]:
        """返回 chunk_id 到相关性分数

        参数:
            db: 异步数据库会话
            dialect_name: 数据库方言名称
            query: 用户查询
            limit: 最大候选数

        返回:
            dict[int, float]: 关键词检索分数
        """
        if dialect_name == "sqlite":
            return await self._search_sqlite(db, query, limit)
        if dialect_name == "postgresql":
            return await self._search_postgres(db, query, limit)
        raise UnsupportedKnowledgeDialectError(dialect_name)

    def _sqlite_fts_query(self, query: str) -> str:
        """生成安全的 SQLite FTS MATCH 查询"""
        normalized = query.strip().lower()
        if not normalized:
            return ""
        terms = [
            term
            for term in normalized.replace("，", " ").replace("。", " ").split()
            if term and all(char.isalnum() or "一" <= char <= "鿿" for char in term)
        ]
        if terms:
            return " OR ".join(terms[:8])
        compact = "".join(
            char for char in normalized if char.isalnum() or "一" <= char <= "鿿"
        )
        return compact[:64]

    async def _search_sqlite(
        self, db: AsyncSession, query: str, limit: int
    ) -> dict[int, float]:
        """SQLite FTS5 关键词检索"""
        fts_query = self._sqlite_fts_query(query)
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
                    LIMIT :limit
                    """
                ),
                {"query": fts_query, "limit": limit},
            )
        except Exception:
            return {}
        scores: dict[int, float] = {}
        for rowid, rank in result.all():
            scores[int(rowid)] = 1.0 / (1.0 + abs(float(rank)))
        return scores

    async def _search_postgres(
        self, db: AsyncSession, query: str, limit: int
    ) -> dict[int, float]:
        """PostgreSQL tsvector 全文检索"""
        try:
            result = await db.execute(
                text(
                    """
                    SELECT id,
                           ts_rank_cd(
                             to_tsvector(
                               'simple',
                               coalesce(title, '') || ' ' || coalesce(content, '') || ' ' || coalesce(source, '')
                             ),
                             plainto_tsquery('simple', :query)
                           ) AS rank
                    FROM knowledge_chunks
                    WHERE to_tsvector(
                            'simple',
                            coalesce(content, '') || ' ' || coalesce(source, '')
                          ) @@ plainto_tsquery('simple', :query)
                    ORDER BY rank DESC
                    LIMIT :limit
                    """
                ),
                {"query": query, "limit": limit},
            )
        except Exception:
            logger.debug("KnowledgeKeywordSearch: PostgreSQL tsquery failed", exc_info=True)
            return {}
        scores: dict[int, float] = {}
        for row_id, rank in result.all():
            if row_id is not None and rank is not None:
                scores[int(row_id)] = float(rank)
        return scores
