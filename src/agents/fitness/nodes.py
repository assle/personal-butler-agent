import json
from datetime import date
from sqlalchemy import select
from langgraph.config import get_config
from src.models.training import TrainingRecord

EXTRACTION_PROMPT = """从用户消息中提取训练记录。返回 JSON 数组，每条记录包含：
- date: 训练日期 YYYY-MM-DD（未指定则用今天）
- muscle_group: 训练部位（胸/背/腿/肩/臂/核心）
- exercise: 动作名称
- sets: 组数（整数）
- reps: 次数（整数）
- weight_kg: 重量kg（自重训练可为null）

如果无法提取任何记录，返回空数组 []。
只返回 JSON，不要有其他文字。"""

PLAN_PROMPT = """你是健身教练。根据用户最近的训练记录和偏好，生成今日训练建议。
考虑：部位轮换（避免连续练同一部位）、用户目标和水平。
用自然语言给出建议部位、推荐动作、组数次数。"""


def _get_llm():
    config = get_config()
    return config["configurable"]["llm"]


def _get_db():
    config = get_config()
    return config["configurable"]["db"]


async def extract_training_records(state: dict) -> dict:
    llm = _get_llm()
    try:
        raw = await llm.chat_json(
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": state["message"]},
            ],
        )
        return {"raw_result": raw}
    except Exception as e:
        return {"error": str(e), "raw_result": None}


async def validate_records(state: dict) -> dict:
    if state.get("error"):
        return {}
    raw = state.get("raw_result", "")
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return {"parsed_items": [], "error": "无法解析训练记录，请确认格式后重试。"}
    if not isinstance(items, list):
        return {"parsed_items": [], "error": "无法解析训练记录，请确认格式后重试。"}
    valid = []
    for item in items:
        required = ["muscle_group", "exercise", "sets", "reps"]
        if not all(k in item for k in required):
            continue
        valid.append(item)
    return {"parsed_items": valid}


async def persist_records(state: dict) -> dict:
    if state.get("error"):
        return {}
    db = _get_db()
    items = state.get("parsed_items", [])
    if not items:
        return {"saved_records": []}
    saved = []
    for item in items:
        try:
            record = TrainingRecord(
                user_id=state["user_id"],
                date=str(item.get("date", date.today().isoformat())),
                muscle_group=str(item["muscle_group"]),
                exercise=str(item["exercise"]),
                sets=int(item["sets"]),
                reps=int(item["reps"]),
                weight_kg=float(item["weight_kg"]) if item.get("weight_kg") is not None else None,
            )
        except (ValueError, TypeError):
            continue
        db.add(record)
        saved.append({
            "muscle_group": record.muscle_group,
            "exercise": record.exercise,
            "sets": record.sets,
            "reps": record.reps,
            "weight_kg": record.weight_kg,
        })
    await db.flush()
    return {"saved_records": saved}


async def format_log_response(state: dict) -> dict:
    saved = state.get("saved_records", [])
    if state.get("error"):
        return {"reply": state["error"]}
    if not saved:
        return {"reply": "未识别到训练记录。示例格式：打卡 今天练胸 卧推80kg5组8次"}
    return {
        "reply": f"已记录 {len(saved)} 条训练：{'、'.join(r['exercise'] for r in saved)}",
        "data": {"records": saved},
    }


async def fetch_training_history(state: dict) -> dict:
    from datetime import date, timedelta
    db = _get_db()
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    result = await db.execute(
        select(TrainingRecord)
        .where(TrainingRecord.user_id == state["user_id"])
        .where(TrainingRecord.date >= cutoff)
        .order_by(TrainingRecord.date.desc())
    )
    recent = result.scalars().all()
    history_text = "\n".join(
        f"- {r.date}: {r.muscle_group} {r.exercise} {r.sets}×{r.reps}"
        + (f" {r.weight_kg}kg" if r.weight_kg else "")
        for r in recent
    ) if recent else "暂无训练记录"
    return {"history_text": history_text}


async def fetch_user_preferences(state: dict) -> dict:
    import json
    db = _get_db()
    from src.models.preference import UserPreference, DEFAULT_PREFERENCES
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == state["user_id"])
    )
    pref = result.scalar_one_or_none()
    pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES
    return {"preferences": pref_json}


async def generate_plan(state: dict) -> dict:
    import json
    llm = _get_llm()
    try:
        prefs = state.get("preferences", {})
        reply = await llm.chat(
            messages=[
                {"role": "system", "content": PLAN_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"用户偏好：{json.dumps(prefs.get('fitness', {}), ensure_ascii=False)}\n"
                        f"最近训练：\n{state.get('history_text', '暂无训练记录')}\n"
                        f"请给出今日训练建议。"
                    ),
                },
            ],
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


async def format_plan_response(state: dict) -> dict:
    if state.get("error"):
        return {"reply": f"生成训练计划失败：{state['error']}"}
    return {"reply": state.get("reply", "无法生成训练计划。")}


def path_condition(state: dict) -> str:
    if state.get("error"):
        return "error_handler"
    intent = state.get("intent", "")
    if intent == "log_training":
        return "log_training"
    elif intent == "today_plan":
        return "today_plan"
    return "error_handler"


def log_path_condition(state: dict) -> str:
    if state.get("error"):
        return "error_handler"
    items = state.get("parsed_items")
    if items is None:
        return "error_handler"
    return "persist"


async def error_handler(state: dict) -> dict:
    return {"reply": state.get("error", "处理请求时发生错误，请稍后重试。")}
