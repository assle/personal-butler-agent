"""
网页解析器
抓取网页 URL 并转成纯文本，去除导航/广告噪声。

Workflow:
  URL → httpx GET → html2text 转换 → 正则去噪 → chunk_text()
"""
from __future__ import annotations

import re

import html2text
import httpx

from src.knowledge.chunking import chunk_text
from src.knowledge.schemas import KnowledgeChunkInput

_NOISE_PATTERNS = [
    re.compile(r"\* \[.*?\]\(#.*?\)"),          # 导航链接
    re.compile(r"\[Skip to content\].*?\n", re.I),
    re.compile(r"\n{3,}"),                       # 多余空行
]


def parse_web(url: str, chunk_size: int = 800, overlap: int = 100) -> list[KnowledgeChunkInput]:
    """抓取网页并解析为 chunk 列表

    参数:
        url: 网页 URL
        chunk_size: 分块大小
        overlap: 重叠大小

    返回:
        list[KnowledgeChunkInput]: 切好的 chunk 列表
    """
    response = httpx.get(url, timeout=15, follow_redirects=True)
    response.raise_for_status()

    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0
    text = converter.handle(response.text)

    for pattern in _NOISE_PATTERNS:
        text = pattern.sub("", text)
    text = text.strip()

    return chunk_text(text, chunk_size=chunk_size, overlap=overlap)
