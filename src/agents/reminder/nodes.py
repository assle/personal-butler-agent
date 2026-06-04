"""
Reminder Agent 节点函数
解析私聊提醒请求、创建群 webhook 提醒、查看提醒列表和取消提醒。

Workflow:
  run_reminder_action 根据 intent 分流
  → 创建提醒时调用 LLM 输出 JSON
  → ReminderService 写库或查询
  → 返回可读回复
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from langgraph.config import get_config

from src.reminders import ReminderCreate


REMINDER_PARSE_PROMPT = """你是提醒解析器，只输出 JSON，不要输出解释。

当前日期时间：{now}
默认时区：Asia/Shanghai
可用目标群：
{targets}

用户会用中文要求创建最终发送到企业微信群 webhook 的提醒。请解析为以下 JSON：
{{
  "target_hint": "用户提到的目标群名或配置名",
  "title": "短标题",
  "message": "到点时提醒用户要做的事，不包含@人",
  "schedule_type": "once 或 cron",
  "run_at": "一次性提醒的 ISO8601 时间，必须带 +08:00；周期性提醒填 null",
  "cron": "周期性提醒的 5 段 crontab；一次性提醒填 null"
}}

规则：
- “提醒我”表示到点 @ 当前私聊用户，不需要解析姓名。
- 如果用户没有说目标群，但事项或文本明显匹配可用目标群名称/别名，可以填写匹配到的 target name；仍无法判断时 target_hint 为空字符串。
- 如果用户说每天/每周/每月，schedule_type 使用 cron。
- 如果用户说具体日期、明天、后天、今晚等一次性时间，schedule_type 使用 once。
- cron 使用北京时间解释，例如每天 8 点是 "0 8 * * *"，每周日 20 点是 "0 20 * * 0"。
- message 只写事项，例如“练腿”“称体重”“总结本周训练”。
- 无法判断时间时，run_at 和 cron 都填 null。
"""


def _extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON 对象

    参数:
        text: LLM 返回的原始文本

    返回:
        dict: 解析出的 JSON 对象
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{.*\}", stripped, flags=re.S)
    if not match:
        raise ValueError("提醒解析失败：模型没有返回 JSON。")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("提醒解析失败：JSON 不是对象。")
    return data


def _target_lines(service) -> str:
    """格式化可用 webhook 目标给 LLM 参考

    参数:
        service: ReminderService 实例

    返回:
        str: 每行一个 target name 和别名
    """
    lines = []
    for target in getattr(service, "_targets", []):
        display_name = (getattr(target, "display_name", None) or "").strip()
        aliases = ", ".join(getattr(target, "aliases", []) or [])
        label = f"{target.name}"
        if display_name:
            label = f"{label}（群名：{display_name}）"
        if aliases:
            lines.append(f"- {label}（别名：{aliases}）")
        else:
            lines.append(f"- {label}")
    return "\n".join(lines) or "（未配置任何 webhook target）"


async def _parse_create_request(message: str, llm, service) -> ReminderCreate:
    """调用 LLM 解析创建提醒请求

    参数:
        message: 用户原始提醒请求
        llm: LLMClient 实例
        service: ReminderService 实例

    返回:
        ReminderCreate: 解析后的创建参数，不含 creator_user_id
    """
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    raw = await llm.chat(
        messages=[
            {
                "role": "system",
                "content": REMINDER_PARSE_PROMPT.format(
                    now=now,
                    targets=_target_lines(service),
                ),
            },
            {"role": "user", "content": message},
        ]
    )
    data = _extract_json(raw)
    target_hint = str(data.get("target_hint", "") or "")
    message_text = str(data.get("message", "") or "")
    if not target_hint:
        target_hint = service.infer_target_hint(f"{message}\n{message_text}")
    return ReminderCreate(
        creator_user_id="",
        target_hint=target_hint,
        title=str(data.get("title", "") or ""),
        message=message_text,
        schedule_type=str(data.get("schedule_type", "") or ""),
        run_at=data.get("run_at"),
        cron=data.get("cron"),
        timezone_name="Asia/Shanghai",
    )


def _format_local_time(value, timezone_name: str) -> str:
    """把数据库 UTC 时间格式化为用户本地时间

    参数:
        value: 数据库中保存的 UTC naive datetime
        timezone_name: 要展示的时区名称

    返回:
        str: 本地时间文本；无时间时返回“无”
    """
    if value is None:
        return "无"
    local_time = value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(timezone_name))
    return local_time.strftime("%Y-%m-%d %H:%M")


def _format_created_reply(reminder, service) -> str:
    """格式化创建成功回复

    参数:
        reminder: 新创建的 Reminder ORM 对象
        service: ReminderService 实例，用于把内部 target name 转成用户可见群名

    返回:
        str: 给私聊用户看的确认文本
    """
    target_text = service.get_target_display_name(reminder.target_name)
    next_text = _format_local_time(reminder.next_run_at, reminder.timezone)
    return (
        f"已创建提醒 #{reminder.id}：{reminder.title}\n"
        f"目标群：{target_text}\n"
        f"提醒对象：@{reminder.mention_user_id}\n"
        f"下次触发：{next_text}（{reminder.timezone}）"
    )


def _format_list_reply(reminders, service) -> str:
    """格式化提醒列表回复

    参数:
        reminders: Reminder ORM 对象列表
        service: ReminderService 实例，用于把内部 target name 转成用户可见群名

    返回:
        str: 给私聊用户看的提醒列表
    """
    if not reminders:
        return "你现在没有启用中的提醒。"
    lines = ["你的提醒："]
    for reminder in reminders:
        target_text = service.get_target_display_name(reminder.target_name)
        next_text = _format_local_time(reminder.next_run_at, reminder.timezone)
        lines.append(
            f"#{reminder.id} {reminder.title}｜{target_text}｜下次 {next_text}（{reminder.timezone}）"
        )
    return "\n".join(lines)


def _extract_reminder_id(message: str) -> int | None:
    """从取消请求中提取提醒 ID

    参数:
        message: 用户取消提醒的请求文本

    返回:
        int | None: 找到的提醒 ID；未找到返回 None
    """
    match = re.search(r"#?\s*(\d+)", message)
    if not match:
        return None
    return int(match.group(1))


async def run_reminder_action(state: dict) -> dict:
    """执行提醒创建、查看或取消操作

    参数:
        state: 包含 intent/message/user_id 的 ReminderState

    返回:
        dict: 包含 reply/data/error 的状态更新
    """
    config = get_config()["configurable"]
    db = config["db"]
    llm = config["llm"]
    service = config["reminder_service"]
    intent = state.get("intent", "")
    message = state.get("message", "")
    user_id = state.get("user_id", "")

    try:
        if intent == "list_reminders":
            reminders = await service.list_user_reminders(db, user_id)
            return {
                "reply": _format_list_reply(reminders, service),
                "data": {"count": len(reminders)},
            }

        if intent == "cancel_reminder":
            reminder_id = _extract_reminder_id(message)
            if reminder_id is None:
                return {"reply": "请告诉我要取消哪个提醒编号，例如“取消 #3”。"}
            reminder = await service.cancel_user_reminder(db, user_id, reminder_id)
            if reminder is None:
                return {"reply": f"没有找到你启用中的提醒 #{reminder_id}。"}
            return {"reply": f"已取消提醒 #{reminder.id}：{reminder.title}"}

        parsed = await _parse_create_request(message, llm, service)
        payload = ReminderCreate(
            creator_user_id=user_id,
            target_hint=parsed.target_hint,
            title=parsed.title,
            message=parsed.message,
            schedule_type=parsed.schedule_type,
            run_at=parsed.run_at,
            cron=parsed.cron,
            timezone_name=parsed.timezone_name,
        )
        reminder = await service.create_reminder(db, payload)
        return {
            "reply": _format_created_reply(reminder, service),
            "data": {"reminder_id": reminder.id},
        }
    except Exception as e:
        return {"reply": f"创建或管理提醒失败：{e}", "error": str(e)}
