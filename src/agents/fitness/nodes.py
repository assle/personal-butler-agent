"""
Fitness Agent 节点函数
每个节点是 StateGraph 中的一个执行单元，负责单一职责

Workflow - log_training 路线:
  extract_training_records → validate_records → persist_records → format_log_response
Workflow - today_plan 路线:
  fetch_training_history → fetch_user_preferences → generate_plan → format_plan_response
控制节点:
  path_condition: 入口路由，根据 intent 分流
  log_path_condition: validate 后的路由，决定入库还是报错
  error_handler: 统一错误处理

节点间通过 FitnessState 字典共享数据，不允许节点直接互相调用
"""
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

PLAN_PROMPT = """你是"铁块教练"，用户的私人健身教练。

性格底色：热血、直接、有股子"再来一组"的劲头，但说到安全动作时就切回认真模式。

说话方式：
- 用老铁/兄弟称呼，别太频繁
- 鼓励要有，但不尬吹——用户划水了也要点出来
- 讲动作细节时切换成简洁清晰的专业口吻
- 可以加 💪 🔥 这类 emoji

回复长度：训练建议 3-5 句，打卡确认 1-2 句。

根据用户最近的训练记录和偏好，生成今日训练建议。
考虑：部位轮换（避免连续练同一部位）、用户目标和水平。

{conversation_context}"""


def _get_llm():
    """从 LangGraph 配置中获取 LLM 客户端

    返回:
        LLMClient: 注入在 configurable 中的 LLM 客户端实例
    """
    config = get_config()
    return config["configurable"]["llm"]


def _get_db():
    """从 LangGraph 配置中获取数据库会话

    返回:
        AsyncSession: 注入在 configurable 中的异步数据库会话
    """
    config = get_config()
    return config["configurable"]["db"]


async def extract_training_records(state: dict) -> dict:
    """调用 LLM 从用户消息中提取训练记录 JSON

    参数:
        state: 包含 message 字段的当前状态

    返回:
        dict: {"raw_result": LLM 返回的 JSON 字符串} 或 {"error": 错误信息}
    """
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
    """校验 LLM 提取的训练记录，过滤不合法条目

    参数:
        state: 包含 raw_result 字段的当前状态

    返回:
        dict: {"parsed_items": 验证通过的记录列表} 或 {"parsed_items": [], "error": 错误提示}
    """
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
    """将验证通过的训练记录写入数据库

    参数:
        state: 包含 parsed_items、user_id 的当前状态

    返回:
        dict: {"saved_records": 已入库的记录列表}
    """
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
    """格式化训练记录入库结果，生成用户可读的回复

    参数:
        state: 包含 saved_records、error 的当前状态

    返回:
        dict: {"reply": 格式化回复文本, "data": {"records": 记录列表}}
    """
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
    """查询用户近一周的训练历史

    参数:
        state: 包含 user_id 的当前状态

    返回:
        dict: {"history_text": 格式化训练历史文本，或 "暂无训练记录"}
    """
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
    """查询用户偏好设置（训练目标、身体数据等）

    参数:
        state: 包含 user_id 的当前状态

    返回:
        dict: {"preferences": 用户偏好字典，无记录时返回默认值}
    """
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
    """调用 LLM 生成今日训练计划

    参数:
        state: 包含 preferences、history_text 的当前状态

    返回:
        dict: {"reply": LLM 生成的训练建议文本} 或 {"error": 错误信息}
    """
    import json
    llm = _get_llm()
    try:
        prefs = state.get("preferences", {})
        context_parts = []
        if state.get("conversation_summary"):
            context_parts.append(f"你们之前对话的摘要：{state['conversation_summary']}")
        conversation_context = "\n".join(context_parts) if context_parts else ""

        messages = [
            {
                "role": "system",
                "content": PLAN_PROMPT.format(
                    conversation_context=conversation_context,
                ),
            },
        ]
        for msg in state.get("recent_messages", []):
            messages.append(msg)
        messages.append({
            "role": "user",
            "content": (
                f"用户偏好：{json.dumps(prefs.get('fitness', {}), ensure_ascii=False)}\n"
                f"最近训练：\n{state.get('history_text', '暂无训练记录')}\n"
                f"请给出今日训练建议。"
            ),
        })

        reply = await llm.chat(messages=messages)
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


async def format_plan_response(state: dict) -> dict:
    """格式化训练计划输出

    参数:
        state: 包含 reply 或 error 的当前状态

    返回:
        dict: {"reply": 格式化后的回复文本}
    """
    if state.get("error"):
        return {"reply": f"生成训练计划失败：{state['error']}"}
    return {"reply": state.get("reply", "无法生成训练计划。")}


def path_condition(state: dict) -> str:
    """入口路由函数，根据 intent 决定走哪条子路线

    参数:
        state: 包含 intent 字段的初始状态

    返回:
        str: "log_training" / "today_plan" / "error_handler"
    """
    if state.get("error"):
        return "error_handler"
    intent = state.get("intent", "")
    if intent == "log_training":
        return "log_training"
    elif intent == "today_plan":
        return "today_plan"
    return "error_handler"


def log_path_condition(state: dict) -> str:
    """验证后路由函数，决定进入 persist 还是 error_handler

    参数:
        state: 包含 parsed_items、error 的当前状态

    返回:
        str: "persist" 或 "error_handler"
    """
    if state.get("error"):
        return "error_handler"
    items = state.get("parsed_items")
    if items is None:
        return "error_handler"
    return "persist"


async def error_handler(state: dict) -> dict:
    """统一错误处理节点，将错误信息转为用户可读回复

    参数:
        state: 包含 error 字段的当前状态

    返回:
        dict: {"reply": 错误提示文本}
    """
    return {"reply": state.get("error", "处理请求时发生错误，请稍后重试。")}
