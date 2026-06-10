"""知识库模块包，提供文档切块、入库和检索服务"""
from src.knowledge.schemas import (
    KnowledgeChunkInput,
    KnowledgeChunkResult,
    KnowledgeIngestRequest,
)
from src.knowledge.chunking import chunk_text
from src.knowledge.embedding import EmbeddingService
from src.knowledge.service import KnowledgeService

__all__ = [
    "EmbeddingService",
    "KnowledgeChunkInput",
    "KnowledgeChunkResult",
    "KnowledgeIngestRequest",
    "KnowledgeService",
    "chunk_text",
]
