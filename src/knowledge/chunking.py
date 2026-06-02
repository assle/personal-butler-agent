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
