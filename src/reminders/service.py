"""
提醒任务服务
封装群 webhook 提醒任务的目标解析、时间标准化、数据库读写和执行状态更新。

Workflow:
1. ReminderAgent 把自然语言解析成 ReminderCreate
2. ReminderService.create_reminder() 解析目标群和 @ 用户并落库
3. SchedulerManager 调用 get_due_reminders() 扫描到期任务
4. 推送完成后调用 mark_success()/mark_failed() 更新下一次执行时间
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from src.models.reminder import Reminder, ReminderRun


@dataclass(frozen=True)
class ReminderCreate:
    """创建提醒所需的结构化字段"""

    # 创建提醒的私聊用户 ID
    creator_user_id: str
    # 用户原话中识别出的目标群名、别名或 target name
    target_hint: str
    # 提醒标题
    title: str
    # 到点推送给群的正文
    message: str
    # 调度类型：once 或 cron
    schedule_type: str
    # 一次性提醒的 ISO 时间字符串
    run_at: str | None = None
    # 周期性提醒的 crontab 表达式
    cron: str | None = None
    # 用户表达时间时使用的时区
    timezone_name: str = "Asia/Shanghai"


class ReminderService:
    """群 webhook 提醒服务，集中管理提醒任务的数据库操作"""

    def __init__(self, webhook_targets: list):
        """初始化提醒服务

        参数:
            webhook_targets: 由 SCHEDULER_TARGETS_FILE 加载出的 webhook target 列表

        返回:
            None
        """
        self._targets = webhook_targets

    def set_targets(self, webhook_targets: list) -> None:
        """更新提醒服务可用的 webhook target 列表

        参数:
            webhook_targets: 最新加载出的 webhook target 列表

        返回:
            None
        """
        self._targets = webhook_targets

    def resolve_target(self, target_hint: str):
        """根据群名、别名或 target name 找到 webhook target

        参数:
            target_hint: 用户输入中的群名、别名或配置名称

        返回:
            WebhookSchedulerTarget | None: 找到则返回目标配置，否则返回 None
        """
        normalized = target_hint.strip().lower()
        enabled_targets = [target for target in self._targets if getattr(target, "enabled", True)]
        if not normalized:
            if len(enabled_targets) == 1:
                return enabled_targets[0]
            return None
        for target in enabled_targets:
            aliases = [target.name, *(getattr(target, "aliases", []) or [])]
            if any(normalized == alias.strip().lower() for alias in aliases):
                return target
        for target in enabled_targets:
            aliases = [target.name, *(getattr(target, "aliases", []) or [])]
            if any(alias.strip().lower() in normalized for alias in aliases if alias.strip()):
                return target
        return None

    def infer_target_hint(self, message: str) -> str:
        """从提醒事项文本中推断目标 webhook target

        参数:
            message: 提醒事项或用户原始提醒文本

        返回:
            str: 推断出的 target name；无法推断时返回空字符串
        """
        normalized = message.strip().lower()
        enabled_targets = [target for target in self._targets if getattr(target, "enabled", True)]
        if len(enabled_targets) == 1:
            return enabled_targets[0].name
        for target in enabled_targets:
            aliases = [target.name, *(getattr(target, "aliases", []) or [])]
            for alias in aliases:
                alias_text = alias.strip().lower()
                if alias_text and alias_text in normalized:
                    return target.name
                alias_core = alias_text.replace("-group", "").replace("群", "")
                if alias_core and alias_core in normalized:
                    return target.name
        return ""

    def resolve_mention_user_id(self, creator_user_id: str, target) -> str:
        """解析群 webhook 中要 @ 的用户 ID

        参数:
            creator_user_id: 私聊回调里的 from.userid
            target: 目标 webhook target 配置

        返回:
            str: 配置覆盖后的 @ 用户 ID；无覆盖时返回 creator_user_id
        """
        overrides = getattr(target, "mention_user_overrides", {}) or {}
        return overrides.get(creator_user_id, creator_user_id)

    def get_target_display_name(self, target_hint: str) -> str:
        """获取 webhook target 面向用户展示的群名

        参数:
            target_hint: target name、别名或用户输入的目标群提示

        返回:
            str: 优先使用 display_name，其次使用第一个别名，最后使用内部 name
        """
        target = self.resolve_target(target_hint)
        if target is None:
            return target_hint
        display_name = (getattr(target, "display_name", None) or "").strip()
        if display_name:
            return display_name
        aliases = getattr(target, "aliases", []) or []
        for alias in aliases:
            alias_text = str(alias).strip()
            if alias_text:
                return alias_text
        return target.name

    async def create_reminder(self, db, payload: ReminderCreate) -> Reminder:
        """创建提醒任务并写入数据库

        参数:
            db: SQLAlchemy 异步数据库会话
            payload: ReminderCreate 结构化创建参数

        返回:
            Reminder: 已 flush、包含主键的提醒对象
        """
        target = self.resolve_target(payload.target_hint)
        if target is None:
            raise ValueError(
                f"找不到目标群“{payload.target_hint}”，请使用已配置的 webhook target 名称或别名。"
            )

        schedule_type = payload.schedule_type.strip().lower()
        if schedule_type not in {"once", "cron"}:
            raise ValueError("提醒调度类型必须是 once 或 cron。")

        run_at = self._parse_run_at(payload.run_at, payload.timezone_name)
        cron = (payload.cron or "").strip() or None
        next_run_at = self._next_run_at(schedule_type, run_at, cron, payload.timezone_name)
        if next_run_at is None:
            raise ValueError("无法计算提醒的下一次触发时间，请确认时间或重复规则。")

        now = datetime.utcnow()
        reminder = Reminder(
            creator_user_id=payload.creator_user_id,
            mention_user_id=self.resolve_mention_user_id(payload.creator_user_id, target),
            target_name=target.name,
            chat_id=target.chat_id or target.name,
            title=payload.title.strip() or payload.message.strip()[:40],
            message=payload.message.strip(),
            schedule_type=schedule_type,
            run_at=run_at,
            cron=cron,
            timezone=payload.timezone_name,
            enabled=True,
            status="scheduled",
            next_run_at=next_run_at,
            created_at=now,
            updated_at=now,
        )
        db.add(reminder)
        await db.flush()
        return reminder

    async def list_user_reminders(self, db, user_id: str, limit: int = 10) -> list[Reminder]:
        """查询用户创建的有效提醒

        参数:
            db: SQLAlchemy 异步数据库会话
            user_id: 当前私聊用户 ID
            limit: 最多返回的提醒数量

        返回:
            list[Reminder]: 按下一次触发时间排序的提醒列表
        """
        result = await db.execute(
            select(Reminder)
            .where(Reminder.creator_user_id == user_id, Reminder.enabled.is_(True))
            .order_by(Reminder.next_run_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def cancel_user_reminder(self, db, user_id: str, reminder_id: int) -> Reminder | None:
        """取消当前用户创建的提醒

        参数:
            db: SQLAlchemy 异步数据库会话
            user_id: 当前私聊用户 ID
            reminder_id: 要取消的提醒 ID

        返回:
            Reminder | None: 找到并取消则返回提醒对象，否则返回 None
        """
        result = await db.execute(
            select(Reminder).where(
                Reminder.id == reminder_id,
                Reminder.creator_user_id == user_id,
                Reminder.enabled.is_(True),
            )
        )
        reminder = result.scalar_one_or_none()
        if reminder is None:
            return None
        reminder.enabled = False
        reminder.status = "cancelled"
        reminder.updated_at = datetime.utcnow()
        await db.flush()
        return reminder

    async def get_due_reminders(self, db, now: datetime | None = None) -> list[Reminder]:
        """查询已经到期、等待推送的提醒

        参数:
            db: SQLAlchemy 异步数据库会话
            now: 当前 UTC 时间；为空时使用 datetime.utcnow()

        返回:
            list[Reminder]: 到期提醒列表
        """
        current = now or datetime.utcnow()
        result = await db.execute(
            select(Reminder)
            .where(
                Reminder.enabled.is_(True),
                Reminder.status == "scheduled",
                Reminder.next_run_at.is_not(None),
                Reminder.next_run_at <= current,
            )
            .order_by(Reminder.next_run_at.asc())
        )
        return list(result.scalars().all())

    async def mark_success(self, db, reminder: Reminder) -> None:
        """记录提醒推送成功并更新下一次触发时间

        参数:
            db: SQLAlchemy 异步数据库会话
            reminder: 已成功推送的提醒对象

        返回:
            None
        """
        now = datetime.utcnow()
        reminder.last_run_at = now
        if reminder.schedule_type == "once":
            reminder.enabled = False
            reminder.status = "executed"
            reminder.next_run_at = None
        else:
            reminder.next_run_at = self._next_run_at(
                "cron",
                None,
                reminder.cron,
                reminder.timezone,
                previous_fire_time=now,
            )
        reminder.updated_at = now
        db.add(
            ReminderRun(
                reminder_id=reminder.id,
                status="success",
                delivered_to=reminder.target_name,
            )
        )
        await db.flush()

    async def mark_failed(self, db, reminder: Reminder, error_message: str) -> None:
        """记录提醒推送失败

        参数:
            db: SQLAlchemy 异步数据库会话
            reminder: 推送失败的提醒对象
            error_message: 失败原因

        返回:
            None
        """
        now = datetime.utcnow()
        reminder.last_run_at = now
        reminder.updated_at = now
        db.add(
            ReminderRun(
                reminder_id=reminder.id,
                status="failed",
                delivered_to=reminder.target_name,
                error_message=error_message[:500],
            )
        )
        await db.flush()

    def format_reminder_message(self, reminder: Reminder) -> str:
        """格式化群 webhook 提醒 markdown 正文

        参数:
            reminder: 到期提醒对象

        返回:
            str: 包含企业微信 markdown @ 语法的提醒正文
        """
        return f"<@{reminder.mention_user_id}> {reminder.message}"

    def _parse_run_at(self, value: str | None, timezone_name: str) -> datetime | None:
        """把 ISO 时间字符串转换为 UTC naive datetime

        参数:
            value: LLM 解析出的 ISO 时间字符串
            timezone_name: 用户表达时间时使用的时区

        返回:
            datetime | None: UTC naive 时间；无输入时返回 None
        """
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)

    def _next_run_at(
        self,
        schedule_type: str,
        run_at: datetime | None,
        cron: str | None,
        timezone_name: str,
        previous_fire_time: datetime | None = None,
    ) -> datetime | None:
        """计算提醒下一次 UTC 触发时间

        参数:
            schedule_type: 调度类型 once 或 cron
            run_at: 一次性提醒 UTC 时间
            cron: 周期性提醒 crontab 表达式
            timezone_name: crontab 解释时使用的时区
            previous_fire_time: 上一次触发时间，用于计算下一次 cron

        返回:
            datetime | None: 下一次 UTC naive 触发时间；无法计算时返回 None
        """
        if schedule_type == "once":
            return run_at
        if not cron:
            return None
        tz = ZoneInfo(timezone_name)
        now_utc = datetime.now(timezone.utc)
        previous = None
        if previous_fire_time is not None:
            previous = previous_fire_time.replace(tzinfo=timezone.utc)
        trigger = CronTrigger.from_crontab(cron, timezone=tz)
        next_fire = trigger.get_next_fire_time(previous, now_utc)
        if next_fire is None:
            return None
        return next_fire.astimezone(timezone.utc).replace(tzinfo=None)
