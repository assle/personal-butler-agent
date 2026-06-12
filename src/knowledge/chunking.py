"""
知识库文档切块工具
将 Markdown/TXT 文本按段落聚合并带 overlap 切块，供 KnowledgeService 入库。

Workflow:
  文档文本 → 去除空白段落 → 按段落边界聚合 → 相邻块 overlap → KnowledgeChunkInput
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


def chunk_text(
    text: str,
    chunk_size: int = 800,
    overlap: int = 100,
) -> list[KnowledgeChunkInput]:
    """将文档文本切成 chunk，段落感知 + 相邻块重叠

    参数:
        text: Markdown 或 TXT 文档文本
        chunk_size: 每个 chunk 的目标最大字符数
        overlap: 相邻块的重叠字符数

    返回:
        list[KnowledgeChunkInput]: 按原文顺序排列的切块列表
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if not current:
            current = para
            continue

        candidate = current + "\n\n" + para
        if len(candidate) > chunk_size:
            chunks.append(current)
            # 保留最后 overlap 字符作为下一个 chunk 的前缀
            if len(current) > overlap:
                current = current[-overlap:] + "\n\n" + para
            else:
                current = para
        else:
            current = candidate

    if current.strip():
        chunks.append(current)

    return [
        KnowledgeChunkInput(
            chunk_index=index,
            content=chunk,
            token_count=_estimate_tokens(chunk),
        )
        for index, chunk in enumerate(chunks)
        if chunk.strip()
    ]
