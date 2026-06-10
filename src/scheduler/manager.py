"""
APScheduler 调度管理器
负责注册 webhook cron job、扫描到期提醒以及管理调度器生命周期。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.reminders import ReminderService
from src.scheduler.client import WebhookPushClient
from src.scheduler.models import WebhookSchedulerTarget
from src.weather import format_weather_report

logger = logging.getLogger(__name__)


class SchedulerManager:
    """定时调度管理器，封装 APScheduler 的生命周期"""

    def __init__(
        self,
        db_session_factory=None,
        webhook_composer_agent=None,
        webhook_client: WebhookPushClient | None = None,
        webhook_targets: list[WebhookSchedulerTarget] | None = None,
        weather_service=None,
        enable_reminder_scan: bool = False,
    ):
        """初始化调度管理器

        参数:
            db_session_factory: 异步数据库会话工厂
            webhook_composer_agent: WebhookComposerAgent 实例，用于生成群 markdown 正文
            webhook_client: 企业微信群 webhook 推送客户端
            webhook_targets: 多群 webhook 定时目标列表
            weather_service: 天气服务，用于定时推送中确定性拼接天气结果
            enable_reminder_scan: 是否注册数据库提醒到期扫描 job

        返回:
            None
        """
        self._db_session_factory = db_session_factory
        self._webhook_composer_agent = webhook_composer_agent
        self._webhook_client = webhook_client
        self._webhook_targets = webhook_targets or []
        self._weather_service = weather_service
        self._reminder_service = ReminderService(self._webhook_targets)
        self._enable_reminder_scan = enable_reminder_scan
        self._scheduler = AsyncIOScheduler()

    def start(self):
        """启动调度器，注册定时任务

        参数:
            无

        返回:
            None
        """
        for target in self._webhook_targets:
            if not target.enabled:
                logger.info("Scheduler webhook: target disabled name=%s", target.name)
                continue
            self._scheduler.add_job(
                self._scheduled_webhook_push,
                trigger=CronTrigger.from_crontab(target.cron),
                id=f"scheduled_webhook_push:{target.name}",
                name=f"群 webhook 定时推送: {target.name}",
                replace_existing=True,
                args=[target],
            )
        if (
            self._enable_reminder_scan
            and self._db_session_factory is not None
            and self._webhook_targets
        ):
            self._scheduler.add_job(
                self._process_due_reminders,
                trigger="interval",
                seconds=60,
                id="reminder_due_scan",
                name="群 webhook 提醒到期扫描",
                replace_existing=True,
                max_instances=1,
            )
        self._scheduler.start()
        logger.info(
            "Scheduler webhook: started, enabled_targets=%s",
            [target.name for target in self._webhook_targets if target.enabled],
        )

    def shutdown(self):
        """关闭调度器

        参数:
            无

        返回:
            None
        """
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler: shutdown")

    async def _scheduled_webhook_push(self, target: WebhookSchedulerTarget):
        """执行单个企业微信群 webhook 定时推送

        参数:
            target: 当前到点的 webhook 推送目标

        返回:
            None
        """
        if self._webhook_client is None:
            logger.error("Scheduler webhook: client is None, cannot push")
            return
        needs_composer = target.mode == "compose"
        if needs_composer and self._webhook_composer_agent is None:
            logger.error("Scheduler webhook: composer agent is None, cannot push")
            return
        async with self._db_session_factory() as db:
            try:
                chat_id = target.chat_id or target.name
                if needs_composer:
                    result = await self._webhook_composer_agent.handle(
                        intent="webhook_compose",
                        message=target.message,
                        user_id=chat_id,
                        db=db,
                        extra_state={"chat_type": "group", "chat_id": chat_id},
                    )
                    content = result.reply
                else:
                    content = await self._build_raw_webhook_content(target)
                ok = await self._webhook_client.send_markdown(
                    target.webhook_url,
                    content,
                )
                if not ok:
                    logger.error(
                        "Scheduler webhook: push failed target name=%s",
                        target.name,
                    )
                    await db.rollback()
                    return
                logger.info(
                    "Scheduler webhook: pushed target name=%s reply=%s",
                    target.name,
                    content[:100],
                )
                await db.commit()
            except Exception as error:
                logger.exception(
                    "Scheduler webhook: push failed target name=%s error=%s",
                    target.name,
                    error,
                )
                await db.rollback()

    async def _build_raw_webhook_content(self, target: WebhookSchedulerTarget) -> str:
        """构造原样推送正文，并按需追加天气查询结果

        参数:
            target: 当前定时推送目标，包含固定正文和可选天气查询

        返回:
            str: 可直接发送到群 webhook 的 markdown 正文
        """
        content = target.message
        if not target.weather_query:
            return content

        weather_text = await self._query_weather_text(target.weather_query)
        return f"{content.rstrip()}\n\n{weather_text}"

    async def _query_weather_text(self, query: str) -> str:
        """执行定时天气查询并格式化为群推送文本

        参数:
            query: 配置中的天气查询文本，例如“今天杭州天气”

        返回:
            str: 天气结果正文；查询失败时返回用户可读的降级提示
        """
        if self._weather_service is None:
            return "天气：当前天气服务不可用，暂时无法查询。"
        report = await self._weather_service.query(query)
        if report is None:
            return f"天气：暂时查不到“{query}”的结果，请稍后再试。"
        return format_weather_report(report)

    async def _process_due_reminders(self):
        """扫描并推送所有到期的群 webhook 提醒

        参数:
            无

        返回:
            None
        """
        if self._webhook_client is None:
            logger.error("Scheduler reminder: client is None, cannot push")
            return
        async with self._db_session_factory() as db:
            reminders = await self._reminder_service.get_due_reminders(db)
            if not reminders:
                return
            for reminder in reminders:
                target = self._reminder_service.resolve_target(reminder.target_name)
                if target is None:
                    await self._reminder_service.mark_failed(
                        db,
                        reminder,
                        f"找不到 webhook target: {reminder.target_name}",
                    )
                    continue
                content = self._reminder_service.format_reminder_message(reminder)
                ok = await self._webhook_client.send_markdown(
                    target.webhook_url,
                    content,
                    mentioned_list=[reminder.mention_user_id],
                )
                if ok:
                    await self._reminder_service.mark_success(db, reminder)
                    logger.info(
                        "Scheduler reminder: pushed reminder_id=%s target=%s",
                        reminder.id,
                        target.name,
                    )
                else:
                    await self._reminder_service.mark_failed(
                        db,
                        reminder,
                        "webhook markdown push failed",
                    )
                    logger.error(
                        "Scheduler reminder: push failed reminder_id=%s target=%s",
                        reminder.id,
                        target.name,
                    )
            await db.commit()
