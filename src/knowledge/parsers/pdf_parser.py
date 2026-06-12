"""
PDF 文档解析器
使用 pypdf 提取文本，按段落边界分块后交给 chunk_text。

Workflow:
  PDF 文件路径 → pypdf.PdfReader 逐页提取 → 拼接段落 → chunk_text()
"""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from src.knowledge.chunking import chunk_text
from src.knowledge.schemas import KnowledgeChunkInput


def parse_pdf(file_bytes: bytes, chunk_size: int = 800, overlap: int = 100) -> list[KnowledgeChunkInput]:
    """解析 PDF 文件为 chunk 列表

    参数:
        file_bytes: PDF 文件字节
        chunk_size: 分块大小
        overlap: 重叠大小

    返回:
        list[KnowledgeChunkInput]: 切好的 chunk 列表
    """
    reader = PdfReader(BytesIO(file_bytes))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text.strip())
    full_text = "\n\n".join(parts)
    return chunk_text(full_text, chunk_size=chunk_size, overlap=overlap)
