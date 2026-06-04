"""
APScheduler 定时调度管理器
管理定时任务的启动、停止和 job 注册

Workflow:
  1. SchedulerManager.start() 启动 AsyncIOScheduler
  2. URL 回调模式下可按 JSON 配置为多个群 webhook 注册独立 cron job
  3. 到点触发 WebhookComposerAgent 生成 markdown 正文
  4. WebhookPushClient 将正文发送到企业微信群 webhook
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.reminders import ReminderService

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)


@dataclass(frozen=True)
class WebhookSchedulerTarget:
    """企业微信群 webhook 定时推送目标"""

    # 目标名称，用于 job id、日志和 agent 上下文，不包含 webhook 密钥
    name: str
    # 当前群的 cron 表达式
    cron: str
    # 企业微信群机器人 webhook 地址，视为敏感信息
    webhook_url: str
    # 到点时交给 WebhookComposerAgent 的配置指令
    message: str
    # 用户可见的群名称，用于私聊确认和提醒列表展示
    display_name: str | None = None
    # 可选群上下文 ID；为空时使用 name
    chat_id: str | None = None
    # 是否启用该目标；配置中可临时关闭单个群
    enabled: bool = True
    # 可选群名别名，用于“宇宙幽默帝国”这类自然语言目标解析
    aliases: tuple[str, ...] = ()
    # 可选 @ 用户覆盖，解决回调 userid 与 webhook @ userid 不一致的情况
    mention_user_overrides: dict[str, str] | None = None


class WebhookPushClient:
    """企业微信群机器人 webhook 推送客户端"""

    def __init__(self, timeout_seconds: int = 10):
        """初始化 webhook 推送客户端

        参数:
            timeout_seconds: HTTP 请求超时时间，单位秒

        返回:
            None
        """
        self._timeout_seconds = timeout_seconds

    async def send_markdown(
        self,
        webhook_url: str,
        content: str,
        mentioned_list: list[str] | None = None,
    ) -> bool:
        """发送 markdown 消息到企业微信群 webhook

        参数:
            webhook_url: 企业微信群机器人 webhook 地址
            content: 要发送的 markdown 内容
            mentioned_list: 可选 @ 用户列表；markdown 内容中仍会保留 <@userid> 语法

        返回:
            bool: 发送成功返回 True，否则返回 False
        """
        if mentioned_list:
            missing_mentions = [
                f"<@{user_id}>"
                for user_id in mentioned_list
                if user_id and f"<@{user_id}>" not in content
            ]
            if missing_mentions:
                content = f"{' '.join(missing_mentions)} {content}"
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(webhook_url, json=payload)
        except httpx.HTTPError:
            logger.info("Scheduler webhook: request failed", exc_info=True)
            return False

        if response.status_code >= 400:
            logger.warning(
                "Scheduler webhook: post failed status=%s body=%s",
                response.status_code,
                response.text[:200],
            )
            return False
        return True


def load_webhook_targets(path: str) -> list[WebhookSchedulerTarget]:
    """从 JSON 文件读取企业微信群 webhook 定时推送目标

    参数:
        path: JSON 配置文件路径，内容为目标数组

    返回:
        list[WebhookSchedulerTarget]: 已启用和未启用目标的结构化配置列表
    """
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise ValueError(f"SCHEDULER_TARGETS_FILE 不存在: {config_path}")

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("SCHEDULER_TARGETS_FILE 必须是 JSON 数组")

    targets: list[WebhookSchedulerTarget] = []
    seen_names: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个 scheduler target 必须是对象")
        name = str(item.get("name", "")).strip()
        display_name = str(item.get("display_name", "")).strip() or None
        cron = str(item.get("cron", "")).strip()
        webhook_url = str(item.get("webhook_url", "")).strip()
        message = str(item.get("message", "")).strip()
        chat_id = str(item.get("chat_id", "")).strip() or None
        enabled = bool(item.get("enabled", True))
        aliases_raw = item.get("aliases", [])
        if aliases_raw is None:
            aliases_raw = []
        if not isinstance(aliases_raw, list):
            raise ValueError(f"第 {index} 个 scheduler target 的 aliases 必须是数组")
        aliases = tuple(str(alias).strip() for alias in aliases_raw if str(alias).strip())
        overrides_raw = item.get("mention_user_overrides", {})
        if overrides_raw is None:
            overrides_raw = {}
        if not isinstance(overrides_raw, dict):
            raise ValueError(
                f"第 {index} 个 scheduler target 的 mention_user_overrides 必须是对象"
            )
        mention_user_overrides = {
            str(key): str(value)
            for key, value in overrides_raw.items()
            if str(key) and str(value)
        }
        if not name or not cron or not webhook_url or not message:
            raise ValueError(
                "scheduler target 必须包含非空 name/cron/webhook_url/message"
            )
        if name in seen_names:
            raise ValueError(f"scheduler target name 重复: {name}")
        seen_names.add(name)
        targets.append(
            WebhookSchedulerTarget(
                name=name,
                display_name=display_name,
                cron=cron,
                webhook_url=webhook_url,
                message=message,
                chat_id=chat_id,
                enabled=enabled,
                aliases=aliases,
                mention_user_overrides=mention_user_overrides,
            )
        )
    return targets

class SchedulerManager:
    """定时调度管理器，封装 APScheduler 的生命周期"""

    def __init__(
        self,
        db_session_factory=None,
        webhook_composer_agent=None,
        webhook_client: WebhookPushClient | None = None,
        webhook_targets: list[WebhookSchedulerTarget] | None = None,
        enable_reminder_scan: bool = False,
    ):
        """初始化调度管理器

        参数:
            db_session_factory: 异步数据库会话工厂
            webhook_composer_agent: WebhookComposerAgent 实例，用于生成群 markdown 正文
            webhook_client: 企业微信群 webhook 推送客户端
            webhook_targets: 多群 webhook 定时目标列表
            enable_reminder_scan: 是否注册数据库提醒到期扫描 job
        """
        self._db_session_factory = db_session_factory
        self._webhook_composer_agent = webhook_composer_agent
        self._webhook_client = webhook_client
        self._webhook_targets = webhook_targets or []
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
        if self._webhook_composer_agent is None:
            logger.error("Scheduler webhook: composer agent is None, cannot push")
            return
        async with self._db_session_factory() as db:
            try:
                chat_id = target.chat_id or target.name
                result = await self._webhook_composer_agent.handle(
                    intent="webhook_compose",
                    message=target.message,
                    user_id=chat_id,
                    db=db,
                    extra_state={"chat_type": "group", "chat_id": chat_id},
                )
                ok = await self._webhook_client.send_markdown(
                    target.webhook_url,
                    result.reply,
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
                    result.reply[:100],
                )
                await db.commit()
            except Exception as e:
                logger.exception(
                    "Scheduler webhook: push failed target name=%s error=%s",
                    target.name,
                    e,
                )
                await db.rollback()

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
