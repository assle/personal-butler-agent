"""
知识库切块测试
验证 Markdown/TXT 文档可以被稳定切成适合检索的文本片段

Workflow:
  原始文本 → chunk_text() → 带标题上下文的 KnowledgeChunkInput 列表
"""
from src.knowledge.chunking import chunk_text


def test_chunk_text_keeps_markdown_heading_context():
    """验证 Markdown 标题会作为上下文进入 chunk

    参数:
        无

    返回:
        None；通过断言确认 chunk 内容包含标题和正文
    """
    text = "# 健身原则\n\n逐步增加负荷。\n\n保持动作标准。"

    chunks = chunk_text(text, max_chars=40)

    assert len(chunks) == 1
    assert chunks[0].content.startswith("# 健身原则")
    assert "逐步增加负荷" in chunks[0].content
    assert "保持动作标准" in chunks[0].content


def test_chunk_text_splits_long_paragraph_groups():
    """验证超出长度限制的段落组会被拆分

    参数:
        无

    返回:
        None；通过断言确认切块数量和序号稳定
    """
    text = "第一段内容很长。\n\n第二段内容也很长。\n\n第三段内容继续很长。"

    chunks = chunk_text(text, max_chars=16)

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert chunks[0].content == "第一段内容很长。"
    assert chunks[1].content == "第二段内容也很长。"
    assert chunks[2].content == "第三段内容继续很长。"


def test_chunk_text_does_not_emit_heading_only_chunk_on_first_overflow():
    """验证标题和首段正文超长时不会生成仅标题 chunk

    参数:
        无

    返回:
        None；通过断言确认正文 chunk 保留标题上下文
    """
    heading = "# 健身原则"
    body = "逐步增加负荷并保持动作标准。"
    text = f"{heading}\n\n{body}"

    chunks = chunk_text(text, max_chars=8)

    assert all(chunk.content != heading for chunk in chunks)
    assert any(
        heading in chunk.content and body in chunk.content
        for chunk in chunks
    )


def test_chunk_text_drops_blank_input():
    """验证空白输入不会生成 chunk

    参数:
        无

    返回:
        None；通过断言确认空白文本返回空列表
    """
    assert chunk_text(" \n\n\t ") == []
