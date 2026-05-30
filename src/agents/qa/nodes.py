import json
from sqlalchemy import select
from langgraph.config import get_config
from src.models.preference import UserPreference, DEFAULT_PREFERENCES

QA_SYSTEM_PROMPT = """你是个人管家助手。根据用户偏好提供个性化回复。

用户偏好：
{preferences}

用友好、简洁的中文回复。"""


async def fetch_preferences(state: dict) -> dict:
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
    if state.get("error"):
        return {"reply": f"抱歉，暂时无法处理：{state['error']}"}
    return {"reply": state.get("reply", "")}
