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
