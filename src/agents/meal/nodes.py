import json
from datetime import date, timedelta
from sqlalchemy import select
from langgraph.config import get_config
from src.models.preference import UserPreference, DEFAULT_PREFERENCES
from src.models.training import TrainingRecord

MEAL_PROMPT = """你是营养师。根据用户信息和最近训练情况，生成一日三餐食谱。

要求：
- 每餐给出具体食物和营养素估算（蛋白质、碳水、脂肪、卡路里）
- 考虑用户热量目标、饮食类型、过敏原
- 有训练日提高蛋白质比例
- 用中文输出，格式如下：

早餐 (≈XXX kcal)
- 食物名 (蛋白质Xg, 碳水Xg, 脂肪Xg)
午餐 (≈XXX kcal)
- ...
晚餐 (≈XXX kcal)
- ..."""


async def fetch_preferences(state: dict) -> dict:
    db = get_config()["configurable"]["db"]
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == state["user_id"])
    )
    pref = result.scalar_one_or_none()
    pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES
    return {"preferences": pref_json}


async def check_training_today(state: dict) -> dict:
    db = get_config()["configurable"]["db"]
    cutoff = (date.today() - timedelta(days=1)).isoformat()
    result = await db.execute(
        select(TrainingRecord)
        .where(TrainingRecord.user_id == state["user_id"])
        .where(TrainingRecord.date >= cutoff)
    )
    trained = result.scalars().all()
    return {"trained_today": bool(trained)}


async def generate_meal_plan(state: dict) -> dict:
    llm = get_config()["configurable"]["llm"]
    import json
    prefs = state.get("preferences", {})
    context = (
        f"用户偏好：{json.dumps(prefs.get('meal', {}), ensure_ascii=False)}\n"
        f"身体数据：{json.dumps(prefs.get('fitness', {}).get('body', {}), ensure_ascii=False)}\n"
        f"训练目标：{prefs.get('fitness', {}).get('goal', '未设定')}\n"
        f"{'今天已训练，需要高蛋白' if state.get('trained_today') else '今天未训练，维持饮食'}"
    )
    try:
        reply = await llm.chat(
            messages=[
                {"role": "system", "content": MEAL_PROMPT},
                {"role": "user", "content": context},
            ],
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


async def format_meal_response(state: dict) -> dict:
    if state.get("error"):
        return {"reply": f"生成食谱失败：{state['error']}"}
    return {"reply": state.get("reply", "无法生成食谱。")}
