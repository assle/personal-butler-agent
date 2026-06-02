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

QA_SYSTEM_PROMPT = """你是"小管家"，用户的私人 AI 助理，陪伴用户日常生活。

性格底色：细心、温暖、偶尔带点小幽默但不油腻。

说话方式：
- 像认识很久的朋友，自然口语化，不要客服腔和机器人感
- 用户偏好中有名字的话，偶尔叫名字显得亲近
- 关心用户的感受和状态，不只是一问一答
- 适当用 emoji 传递情绪，不泛滥
- 不知道就说不知道，不要编

回复长度：日常聊天 2-4 句即可，深入问题可以详细展开。

用户档案（来自系统记录）：
{preferences}

{conversation_context}"""


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
        context_parts = []
        if state.get("conversation_summary"):
            context_parts.append(f"你们之前对话的摘要：{state['conversation_summary']}")
        if state.get("recent_messages"):
            context_parts.append("最近对话记录见下方。")
        conversation_context = "\n".join(context_parts) if context_parts else "（暂无历史对话）"

        messages = [
            {
                "role": "system",
                "content": QA_SYSTEM_PROMPT.format(
                    preferences=json.dumps(state.get("preferences", {}), ensure_ascii=False),
                    conversation_context=conversation_context,
                ),
            },
        ]
        for msg in state.get("recent_messages", []):
            messages.append(msg)
        messages.append({"role": "user", "content": state["message"]})

        reply = await llm.chat(messages=messages)
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
