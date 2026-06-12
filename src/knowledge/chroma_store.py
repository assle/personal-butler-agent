"""
Chroma 向量存储封装
提供 collection 初始化、chunk 索引、语义检索和 metadata 过滤。

Workflow:
  ingest() 之后 → index_chunks() 批量写入 Chroma
  search() 中 → query() 向量检索 + metadata 过滤
"""
from __future__ import annotations

import logging
from pathlib import Path

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "knowledge_chunks"
_DEFAULT_PERSIST_DIR = Path("chroma_data")


class ChromaStore:
    """Chroma 向量存储，嵌入式模式"""

    def __init__(self, persist_dir: str | None = None):
        """初始化 Chroma 客户端和 collection

        参数:
            persist_dir: 数据目录；默认 ./chroma_data

        返回:
            None
        """
        directory = str(persist_dir or _DEFAULT_PERSIST_DIR)
        self._client = chromadb.PersistentClient(
            path=directory,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Chroma store: initialized at %s", directory)

    def index_chunks(
        self,
        chunks: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """批量写入 chunk 到 Chroma collection

        参数:
            chunks: 每个元素是 dict(chunk_id, document_id, title, source,
                    scope_type, scope_id, domain, chunk_index, content)
            embeddings: 与 chunks 一一对应的向量列表

        返回:
            None
        """
        if not chunks:
            return
        ids = [
            f"doc_{c['document_id']}_chunk_{c['chunk_index']}"
            for c in chunks
        ]
        metadatas = [
            {
                "chunk_id": c["chunk_id"],
                "document_id": c["document_id"],
                "scope_type": c["scope_type"],
                "scope_id": c.get("scope_id") or "",
                "domain": c["domain"],
                "source": c["source"],
                "title": c["title"],
                "chunk_index": c["chunk_index"],
            }
            for c in chunks
        ]
        documents = [c["content"] for c in chunks]

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )
        logger.info("Chroma store: indexed %d chunks", len(chunks))

    def delete_by_document(self, document_id: int) -> None:
        """删除指定文档的所有 chunk

        参数:
            document_id: SQLite 文档 ID

        返回:
            None
        """
        self._collection.delete(
            where={"document_id": document_id}
        )
        logger.info("Chroma store: deleted chunks for document_id=%s", document_id)

    def query(
        self,
        query_embedding: list[float],
        scope_type: str,
        scope_id: str | None,
        domains: list[str],
        n_results: int = 20,
    ) -> list[dict]:
        """向量检索 + metadata 权限过滤

        参数:
            query_embedding: 查询向量
            scope_type: "single" 或 "group"，决定可见范围
            scope_id: 用户 ID 或群 ID
            domains: 允许的领域标签
            n_results: 返回最大条数

        返回:
            list[dict]: [{chunk_id, document_id, title, source, content, score}, ...]
        """
        where_clause = _build_scope_filter(scope_type, scope_id, domains)
        try:
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where_clause,
                include=["metadatas", "documents", "distances"],
            )
        except Exception:
            logger.warning("Chroma store: query failed, returning empty", exc_info=True)
            return []

        if not results["ids"] or not results["ids"][0]:
            return []

        out = []
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]
            score = 1.0 / (1.0 + distance)  # cosine distance → similarity
            out.append({
                "chunk_id": meta.get("chunk_id", 0),
                "document_id": meta.get("document_id", 0),
                "title": meta.get("title", ""),
                "source": meta.get("source", ""),
                "content": results["documents"][0][i],
                "score": score,
            })
        return out

    def count(self) -> int:
        """返回 collection 中条目总数

        参数:
            无

        返回:
            int: 条目数
        """
        return self._collection.count()


def _build_scope_filter(
    scope_type: str,
    scope_id: str | None,
    domains: list[str],
) -> dict | None:
    """构建 Chroma metadata where 条件

    参数:
        scope_type: "single" 或 "group"
        scope_id: 用户/群 ID
        domains: 允许的领域

    返回:
        dict | None: Chroma where 子句；无过滤时返回 None
    """
    conditions: list[dict] = []

    # 领域过滤
    if len(domains) == 1:
        conditions.append({"domain": domains[0]})
    elif len(domains) > 1:
        conditions.append({"$or": [{"domain": d} for d in domains]})

    # 权限过滤
    if scope_type == "group":
        if scope_id:
            scope_cond: dict = {
                "$or": [
                    {"scope_type": "public"},
                    {"$and": [
                        {"scope_type": "group"},
                        {"scope_id": scope_id},
                    ]},
                ]
            }
            conditions.append(scope_cond)
        else:
            conditions.append({"scope_type": "public"})
    else:
        scope_cond = {
            "$or": [
                {"scope_type": "public"},
                {"$and": [
                    {"scope_type": "user"},
                    {"scope_id": scope_id or ""},
                ]},
            ]
        }
        conditions.append(scope_cond)

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}
