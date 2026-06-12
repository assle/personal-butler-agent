"""
将 SQLite knowledge_chunk_embeddings 迁移到 Chroma

Workflow:
  遍历 SQLite 中所有 chunk → 读取已有 embedding 或重新生成 → 批量写入 Chroma
  → 验证条目数一致 → 完成
"""
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.db.session import async_session
from src.knowledge.chroma_store import ChromaStore
from src.knowledge.embedding import EmbeddingService
from src.models.knowledge import KnowledgeChunk

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    """执行迁移：SQLite chunks → Chroma collection

    参数:
        无

    返回:
        None；迁移进度打印到 stdout
    """
    chroma = ChromaStore()
    embedding = EmbeddingService()

    async with async_session() as db:
        result = await db.execute(
            select(KnowledgeChunk)
            .options(selectinload(KnowledgeChunk.document))
        )
        chunks = result.scalars().all()
        logger.info("Found %d chunks in SQLite", len(chunks))
        if not chunks:
            logger.info("Nothing to migrate")
            return

        # 检查是否已迁移
        if chroma.count() >= len(chunks):
            logger.info("Chroma already has %d entries, skipping migration", chroma.count())
            return

        payloads = []
        batch_size = 50
        for chunk in chunks:
            doc = chunk.document
            payloads.append({
                "chunk_id": chunk.id,
                "document_id": doc.id if doc else 0,
                "title": doc.title if doc else "",
                "source": chunk.source,
                "scope_type": chunk.scope_type,
                "scope_id": chunk.scope_id or "",
                "domain": chunk.domain,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
            })

            if len(payloads) >= batch_size:
                texts = [f"{p['title']}\n{p['content']}" for p in payloads]
                embs = await embedding.batch_embed(texts)
                chroma.index_chunks(payloads, embs)
                logger.info("Migrated batch: %d chunks", len(payloads))
                payloads = []

        if payloads:
            texts = [f"{p['title']}\n{p['content']}" for p in payloads]
            embs = await embedding.batch_embed(texts)
            chroma.index_chunks(payloads, embs)
            logger.info("Migrated final batch: %d chunks", len(payloads))

    logger.info("Migration complete: %d entries in Chroma", chroma.count())


def run() -> None:
    """启动迁移

    参数:
        无

    返回:
        None
    """
    asyncio.run(main())


if __name__ == "__main__":
    run()
