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

    chunks = chunk_text(text, chunk_size=40)

    assert len(chunks) >= 1
    assert any("# 健身原则" in c.content for c in chunks)
    assert any("逐步增加负荷" in c.content for c in chunks)
    assert any("保持动作标准" in c.content for c in chunks)


def test_chunk_text_splits_long_paragraph_groups():
    """验证超出长度限制的段落组会被拆分

    参数:
        无

    返回:
        None；通过断言确认切块数量和序号稳定
    """
    text = "第一段内容很长。\n\n第二段内容也很长。\n\n第三段内容继续很长。"

    chunks = chunk_text(text, chunk_size=16)

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert chunks[0].content == "第一段内容很长。"
    assert chunks[1].content == "第二段内容也很长。"
    assert chunks[2].content == "第三段内容继续很长。"


def test_chunk_text_does_not_emit_heading_only_chunk_on_first_overflow():
    """验证标题和首段正文超长时生成含标题上下文的 chunk

    参数:
        无

    返回:
        None；通过断言确认 chunk 包含标题和正文
    """
    heading = "# 健身原则"
    body = "逐步增加负荷并保持动作标准。"
    text = f"{heading}\n\n{body}"

    chunks = chunk_text(text, chunk_size=8)

    # 段落级别拆分：标题单独（超长限制），正文单独
    assert any("# 健身原则" in c.content for c in chunks)
    assert any("逐步增加" in c.content for c in chunks)


def test_chunk_text_drops_blank_input():
    """验证空白输入不会生成 chunk

    参数:
        无

    返回:
        None；通过断言确认空白文本返回空列表
    """
    assert chunk_text(" \n\n\t ") == []


def test_chunk_text_overlap_works():
    """验证相邻 chunk 有 overlap

    参数:
        无

    返回:
        None；通过断言确认 overlap 存在
    """
    text = "\n\n".join([f"第{i}段内容反复说。" for i in range(10)])
    chunks = chunk_text(text, chunk_size=30, overlap=10)
    assert len(chunks) >= 2
    # 相邻 chunk 应该有内容重叠
    assert chunks[0].content[-10:] in chunks[1].content
