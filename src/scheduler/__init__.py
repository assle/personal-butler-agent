"""
APScheduler 定时调度管理器
管理定时任务的启动、停止和 job 注册

Workflow:
  1. SchedulerManager.start() 启动 AsyncIOScheduler
  2. 注册 scheduled_push job，到点触发 agent 管线
  3. agent 处理后通过 ws_client.push_message() 推送到目标
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)


class SchedulerManager:
    """定时调度管理器，封装 APScheduler 的生命周期"""

    def __init__(
        self,
        ws_client,
        agent_registry,
        cron_expression: str,
        target_type: str,
        target_id: str,
        message: str,
        intent: str,
        db_session_factory,
    ):
        """初始化调度管理器

        参数:
            ws_client: WeComWSClient 实例，用于推送消息
            agent_registry: AgentRegistry 实例
            cron_expression: cron 表达式（如 "0 9 * * *"）
            target_type: 推送目标类型 "single" / "group"
            target_id: 推送目标 userid 或 chatid
            message: 发给 agent 的触发消息
            intent: agent intent 标识
            db_session_factory: 异步数据库会话工厂
        """
        self._ws = ws_client
        self._agent_registry = agent_registry
        self._cron = cron_expression
        self._target_type = target_type
        self._target_id = target_id
        self._message = message
        self._intent = intent
        self._db_session_factory = db_session_factory
        self._scheduler = AsyncIOScheduler()

    def start(self):
        """启动调度器，注册定时任务"""
        self._scheduler.add_job(
            self._scheduled_push,
            trigger=CronTrigger.from_crontab(self._cron),
            id="scheduled_push",
            name="定时推送",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "Scheduler: started, cron=%s, target=%s=%s, intent=%s, msg=%s",
            self._cron, self._target_type, self._target_id,
            self._intent, self._message,
        )

    def shutdown(self):
        """关闭调度器"""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler: shutdown")

    async def _scheduled_push(self):
        """定时推送 job：触发 agent 管线 → WS 主动推送"""
        if self._ws is None:
            logger.error("Scheduler: ws_client is None, cannot push")
            return
        agent = self._agent_registry.get(self._intent)
        if agent is None:
            logger.error("Scheduler: agent not found for intent=%s", self._intent)
            return
        async with self._db_session_factory() as db:
            try:
                result = await agent.handle(
                    intent=self._intent,
                    message=self._message,
                    user_id=self._target_id,
                    db=db,
                    extra_state={"chat_type": self._target_type},
                )
                await self._ws.push_message(
                    target_type=self._target_type,
                    target_id=self._target_id,
                    msgtype="markdown",
                    content=result.reply,
                )
                logger.info(
                    "Scheduler: pushed to %s=%s, reply=%s",
                    self._target_type, self._target_id, result.reply[:100],
                )
                await db.commit()
            except Exception as e:
                logger.exception("Scheduler: push failed: %s", e)
                await db.rollback()
