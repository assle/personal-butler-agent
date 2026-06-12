"""
画像碎片提取器
从每条用户消息中旁路异步提取偏好、事实、习惯和关系碎片。

Workflow:
  _should_extract() 预过滤 → EXTRACT_FRAGMENTS_PROMPT 让 LLM 提取
  → 返回 [{type, content, signal_strength}] 供 MemoryService.add_fragment() 消费
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

EXTRACT_FRAGMENTS_PROMPT = """你是用户画像碎片提取器。从用户的消息中提取可能反映用户偏好、事实、习惯或关系的碎片信息。

用户消息：
{message}

该用户已有的画像摘要：
{profile_summary}

提取规则：
- preference（偏好）：用户喜欢/不喜欢什么，对事物的态度
- fact（事实）：关于用户的客观信息（地点、职业、技能、使用的工具等）
- habit（习惯）：反复出现的行为模式（"每天都..."、"习惯了..."）
- relationship（关系）：用户与其他人的关联
- signal_strength（信号强度 0.1~1.0）：越明确越高。例如"我不喝咖啡"=0.9，"可能要去杭州"=0.3
- 纯事实查询（天气、知识问答）中的隐含信息也可提取，但 signal_strength 应较低
- 只提取关于用户本人的信息，不提取临时一次性信息
- 没有值得提取的信息时返回空数组

返回 JSON 数组，不要返回其他内容：
[{"type": "preference", "content": "用户不喝咖啡", "signal_strength": 0.9}]"""

# 预过滤关键词：消息必须包含至少一个才进入 LLM 提取
_SHOULD_EXTRACT_PATTERNS = [
    "我", "喜欢", "不喜欢", "讨厌", "爱", "觉得", "想",
    "每天", "经常", "总是", "从来", "习惯",
    "同事", "朋友", "老板", "领导", "家人",
    "工作", "学习", "住在", "在杭州", "在北京", "在上海",
    "做", "搞", "弄", "写", "会", "能",
]


def _should_extract(message: str) -> bool:
    """预过滤：判断消息是否值得进入 LLM 提取

    参数:
        message: 用户消息文本

    返回:
        bool: 是否应提取
    """
    text = message.strip()
    if len(text) < 5:
        return False
    return any(pattern in text for pattern in _SHOULD_EXTRACT_PATTERNS)


async def extract_fragments(
    message: str,
    profile_summary: str,
    llm: Any,
) -> list[dict]:
    """从用户消息中提取画像碎片

    参数:
        message: 用户原始消息文本
        profile_summary: 已有画像的摘要文本（避免重复提取）
        llm: LLMClient 实例，需支持 chat() 方法

    返回:
        list[dict]: [{"type": "preference", "content": "...", "signal_strength": 0.9}, ...]
    """
    if not _should_extract(message):
        return []

    prompt = EXTRACT_FRAGMENTS_PROMPT.format(
        message=message,
        profile_summary=profile_summary or "（暂无已有画像）",
    )

    try:
        raw = await llm.chat(
            messages=[
                {"role": "system", "content": "只返回 JSON 数组，不要返回其他内容。提取不到信息时返回 []。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        # 清理可能的 markdown 代码块包裹
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        fragments = json.loads(raw)
        if not isinstance(fragments, list):
            return []
        valid_types = {"preference", "fact", "habit", "relationship"}
        return [
            {
                "type": f["type"],
                "content": str(f["content"]),
                "signal_strength": max(0.1, min(1.0, float(f.get("signal_strength", 0.5)))),
            }
            for f in fragments
            if isinstance(f, dict) and f.get("type") in valid_types and f.get("content")
        ]
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.debug("Memory: fragment extraction parse error: %s", e)
        return []
    except Exception as e:
        logger.warning("Memory: fragment extraction failed: %s", e)
        return []


def build_profile_summary(grouped_profiles: dict[str, list[dict]]) -> str:
    """将分组画像构建为摘要文本，供提取器使用

    参数:
        grouped_profiles: get_profiles_grouped() 的返回值

    返回:
        str: 可嵌入提取 prompt 的摘要
    """
    type_labels = {
        "preference": "偏好",
        "fact": "事实",
        "habit": "习惯",
        "relationship": "关系",
    }
    lines = []
    for profile_type, profiles in grouped_profiles.items():
        if not profiles:
            continue
        label = type_labels.get(profile_type, profile_type)
        items = [p["content"] for p in profiles[:5]]
        lines.append(f"- {label}: {', '.join(items)}")
    return "\n".join(lines) if lines else "暂无已有画像"
