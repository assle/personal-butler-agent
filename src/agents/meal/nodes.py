"""
Meal Agent 节点函数
每个节点是 StateGraph 中的一个执行单元，负责单一职责

Workflow:
  fetch_preferences → check_training_today → generate_meal_plan → format_meal_response

节点间通过 MealState 字典共享数据，不允许节点直接互相调用
"""
import json
from datetime import date, timedelta
from sqlalchemy import select
from langgraph.config import get_config
from src.models.preference import UserPreference, DEFAULT_PREFERENCES
from src.models.training import TrainingRecord

MEAL_PROMPT = """你是"小厨"，用户的私人营养顾问。

性格底色：细心、讲究、对食物有热情，聊到好吃的会兴奋但不过分。

说话方式：
- 讲营养知识时像科普博主：易懂、有趣、不吓人
- 推荐食谱时带一点画面感（"鸡胸肉煎到两面金黄..."）
- 理解用户的饮食偏好和禁忌，不强行说教
- 偶尔用 🍳 🥗 这类食物 emoji

回复长度：一日三餐推荐 5-8 句，简单问答 2-3 句。

根据用户信息和最近训练情况，生成一日三餐食谱。

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
- ...

{conversation_context}"""


async def fetch_preferences(state: dict) -> dict:
    """查询用户饮食偏好（热量目标、饮食类型、过敏原等）

    参数:
        state: 包含 user_id 的当前状态

    返回:
        dict: {"preferences": 用户偏好字典}
    """
    db = get_config()["configurable"]["db"]
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == state["user_id"])
    )
    pref = result.scalar_one_or_none()
    pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES
    return {"preferences": pref_json}


async def check_training_today(state: dict) -> dict:
    """检查用户今天是否有训练记录

    参数:
        state: 包含 user_id 的当前状态

    返回:
        dict: {"trained_today": bool，影响食谱的蛋白质比例}
    """
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
    """调用 LLM 生成一日三餐食谱

    参数:
        state: 包含 preferences、trained_today 的当前状态

    返回:
        dict: {"reply": LLM 生成的食谱文本} 或 {"error": 错误信息}
    """
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
        context_parts = []
        if state.get("conversation_summary"):
            context_parts.append(f"你们之前对话的摘要：{state['conversation_summary']}")
        conversation_context = "\n".join(context_parts) if context_parts else ""

        messages = [
            {
                "role": "system",
                "content": MEAL_PROMPT.format(
                    conversation_context=conversation_context,
                ),
            },
        ]
        for msg in state.get("recent_messages", []):
            messages.append(msg)
        messages.append({"role": "user", "content": context})

        reply = await llm.chat(messages=messages)
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


async def format_meal_response(state: dict) -> dict:
    """格式化食谱输出

    参数:
        state: 包含 reply 或 error 的当前状态

    返回:
        dict: {"reply": 格式化后的食谱文本或错误提示}
    """
    if state.get("error"):
        return {"reply": f"生成食谱失败：{state['error']}"}
    return {"reply": state.get("reply", "无法生成食谱。")}
