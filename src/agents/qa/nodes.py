"""
QA Agent 节点函数
每个节点是 StateGraph 中的一个执行单元，负责单一职责

Workflow:
  fetch_preferences → generate_qa_response → format_qa_response
  获取用户偏好的 fitness 和 meal 摘要后注入 system prompt，实现个性化问答
"""
import json
from sqlalchemy import select
from langgraph.config import get_config
from src.models.preference import UserPreference, DEFAULT_PREFERENCES

QA_SYSTEM_PROMPT = """你是个人管家助手。根据用户偏好提供个性化回复。

用户偏好：
{preferences}

用友好、简洁的中文回复。"""


async def fetch_preferences(state: dict) -> dict:
    """查询用户偏好（fitness + meal 摘要），用于个性化问答

    参数:
        state: 包含 user_id 的当前状态

    返回:
        dict: {"preferences": {"fitness": ..., "meal": ...}}
    """
    db = get_config()["configurable"]["db"]
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == state["user_id"])
    )
    pref = result.scalar_one_or_none()
    pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES
    preferences_summary = {
        "fitness": pref_json.get("fitness", {}),
        "meal": pref_json.get("meal", {}),
    }
    return {"preferences": preferences_summary}


async def generate_qa_response(state: dict) -> dict:
    """调用 LLM 生成个性化问答回复

    参数:
        state: 包含 preferences、message 的当前状态

    返回:
        dict: {"reply": LLM 生成的回复文本} 或 {"error": 错误信息}
    """
    llm = get_config()["configurable"]["llm"]
    import json
    try:
        reply = await llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": QA_SYSTEM_PROMPT.format(
                        preferences=json.dumps(state.get("preferences", {}), ensure_ascii=False)
                    ),
                },
                {"role": "user", "content": state["message"]},
            ],
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


async def format_qa_response(state: dict) -> dict:
    """格式化 QA 回复输出

    参数:
        state: 包含 reply 或 error 的当前状态

    返回:
        dict: {"reply": 格式化后的回复文本}
    """
    if state.get("error"):
        return {"reply": f"抱歉，暂时无法处理：{state['error']}"}
    return {"reply": state.get("reply", "")}
