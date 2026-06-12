"""
查询重写和 LLM 重排序
增强检索管线：查询重写多角度召回 + pointwise 精排候选集。

Workflow:
  search() → rewrite_query() 生成变体
  → 各路粗筛合并 → rerank_chunks() LLM 精排
  → 返回 top-K
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """将用户查询改写为 2-3 个语义相似但表达不同的变体。

原始查询：{query}

返回 JSON 字符串数组，不要返回其他内容：
["变体1", "变体2", "变体3"]"""


async def rewrite_query(query: str, llm: Any) -> list[str]:
    """将用户查询改写为多个变体，提高召回覆盖率

    参数:
        query: 用户原始查询
        llm: LLMClient 实例

    返回:
        list[str]: [原始查询, 变体1, 变体2, ...]，失败时返回 [原始查询]
    """
    prompt = REWRITE_PROMPT.format(query=query)
    try:
        raw = await llm.chat(
            messages=[
                {"role": "system", "content": "只返回 JSON 数组。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        variants = json.loads(raw)
        if isinstance(variants, list) and len(variants) > 0:
            seen = {query}
            result = [query]
            for v in variants:
                v_str = str(v).strip()
                if v_str and v_str not in seen:
                    seen.add(v_str)
                    result.append(v_str)
            logger.info("Query rewrite: %d variants from '%s'", len(result), query[:60])
            return result[:4]  # 最多 4 个变体
    except Exception:
        logger.warning("Query rewrite: failed, using original query only")
    return [query]


RERANK_PROMPT = """评估以下文本片段与用户查询的相关性，逐条打分。

用户查询：{query}

候选片段：
{chunks_text}

打分规则：
- 10 分：完全回答了查询，包含关键信息
- 7-9 分：高度相关，大部分信息匹配
- 4-6 分：部分相关，有参考价值
- 1-3 分：基本不相关
- 0 分：完全不相关

返回 JSON 对象，key 为 chunk 编号，value 为分数：
{{"0": 9, "1": 4, "2": 7}}"""


async def rerank_chunks(
    query: str,
    candidates: list[dict],
    llm: Any,
    top_k: int = 5,
) -> list[dict]:
    """用 LLM 对候选 chunk 做相关性精排

    参数:
        query: 用户原始查询
        candidates: 粗筛后的候选 chunk 列表，每个元素含 content/title/source/score
        llm: LLMClient 实例
        top_k: 返回条数

    返回:
        list[dict]: 按 LLM 相关性分数降序排列的 top-K
    """
    if len(candidates) <= top_k:
        return candidates

    # 构建编号列表
    chunks_text = "\n\n".join(
        f"--- 片段 {i} ---\n{c['content'][:500]}"
        for i, c in enumerate(candidates)
    )
    prompt = RERANK_PROMPT.format(query=query[:200], chunks_text=chunks_text)

    try:
        raw = await llm.chat(
            messages=[
                {"role": "system", "content": "只返回 JSON 对象。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        scores = json.loads(raw)
        if not isinstance(scores, dict):
            raise ValueError("Expected JSON object")

        for i, c in enumerate(candidates):
            c["relevance_score"] = float(scores.get(str(i), 0))

        candidates.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        logger.info("LLM re-rank: %d candidates -> top-%d", len(candidates), top_k)
        return candidates[:top_k]
    except Exception:
        logger.warning("LLM re-rank failed, falling back to coarse scores")
        candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
        return candidates[:top_k]
