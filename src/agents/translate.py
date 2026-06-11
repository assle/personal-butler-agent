"""
翻译工具函数
调用 LLM 将文本翻译成任意目标语言，供私聊 tool 和群聊节点共用。

Workflow:
  私聊: PrivateButlerAgent tool → translate_text()
  群聊: GroupMentionAgent translate_node → translate_text()
"""
from __future__ import annotations


TRANSLATE_PROMPT = """你是翻译助手。把用户输入翻译成{target_lang}，只返回译文，不要解释，不要添加任何额外内容。"""


async def translate_text(text: str, target_lang: str, llm) -> str:
    """调用 LLM 翻译文本到目标语言

    参数:
        text: 待翻译的文本
        target_lang: 目标语言描述，例如"英文"、"日文"、"法文"
        llm: LLMClient 实例

    返回:
        str: 翻译后的文本
    """
    result = await llm.chat(
        messages=[
            {"role": "system", "content": TRANSLATE_PROMPT.format(target_lang=target_lang)},
            {"role": "user", "content": text},
        ],
    )
    return result.strip()
