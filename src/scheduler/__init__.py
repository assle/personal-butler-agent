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
        intent_router=None,
    ):
        """初始化调度管理器

        参数:
            ws_client: WeComWSClient 实例，用于推送消息
            agent_registry: AgentRegistry 实例
            cron_expression: cron 表达式（如 "0 9 * * *"）
            target_type: 推送目标类型，| 分隔多个值（如 "single|group"）
            target_id: 推送目标 ID，| 分隔多个值（如 "user1|chatid1"）
            message: 发给 agent 的触发消息，| 分隔多值（单值广播，多值需与目标数匹配）
            intent: agent intent 标识，| 分隔多值（空字符串表示自动路由）
            db_session_factory: 异步数据库会话工厂
            intent_router: IntentRouter 实例，当 intent 为空时自动路由（可选，默认 None）
        """
        self._ws = ws_client
        self._agent_registry = agent_registry
        self._cron = cron_expression
        self._message = message
        self._intent = intent
        self._db_session_factory = db_session_factory
        self._intent_router = intent_router
        self._scheduler = AsyncIOScheduler()

        # 解析 | 分隔的多目标配置，按位置配对
        types = [t.strip() for t in target_type.split("|") if t.strip()]
        ids = [i.strip() for i in target_id.split("|") if i.strip()]
        if len(types) != len(ids):
            raise ValueError(
                f"SCHEDULER_TARGET_TYPE 与 SCHEDULER_TARGET_ID 数量不匹配: "
                f"{len(types)} 个类型 vs {len(ids)} 个 ID"
            )
        if not types:
            raise ValueError("SCHEDULER_TARGET_ID 不能为空")

        # 解析消息配置（| 分隔，单值广播，多值需与目标数匹配）
        messages_raw = [m.strip() for m in message.split("|")]
        if len(messages_raw) == 1:
            messages = messages_raw * len(types)
        else:
            if len(messages_raw) != len(types):
                raise ValueError(
                    f"SCHEDULER_MESSAGE 与 SCHEDULER_TARGET_ID 数量不匹配: "
                    f"{len(messages_raw)} 条消息 vs {len(types)} 个目标"
                )
            messages = messages_raw

        # 解析意图配置（| 分隔，空字符串/空位表示自动路由）
        intents_raw = [i.strip() for i in intent.split("|")]
        if len(intents_raw) == 1:
            intents = intents_raw * len(types)
        else:
            if len(intents_raw) != len(types):
                raise ValueError(
                    f"SCHEDULER_INTENT 与 SCHEDULER_TARGET_ID 数量不匹配: "
                    f"{len(intents_raw)} 个意图 vs {len(types)} 个目标"
                )
            intents = intents_raw

        # 每个目标: (类型, ID, 消息, 意图)
        self._targets = list(zip(types, ids, messages, intents))

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
            "Scheduler: started, cron=%s, targets=%s",
            self._cron, self._targets,
        )

    def shutdown(self):
        """关闭调度器"""
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler: shutdown")

    async def _scheduled_push(self):
        """定时推送 job：遍历所有目标，对每个目标触发 agent 管线 → WS 主动推送

        对每个目标：
          1. 如果 intent 为空且有 intent_router，自动路由决定意图
          2. 查找 agent，未找到则跳过
          3. 调用 agent.handle() 处理
          4. 通过 WS 推送结果
        """
        if self._ws is None:
            logger.error("Scheduler: ws_client is None, cannot push")
            return
        async with self._db_session_factory() as db:
            for target_type, target_id, msg, intent in self._targets:
                try:
                    # 解析意图：优先使用配置值，为空时自动路由
                    resolved_intent = intent
                    if not resolved_intent and self._intent_router is not None:
                        resolved_intent, _ = await self._intent_router.route(msg)
                        logger.info(
                            "Scheduler: auto-routed intent=%s for msg=%s",
                            resolved_intent, msg[:50],
                        )

                    agent = self._agent_registry.get(resolved_intent)
                    if agent is None:
                        logger.error(
                            "Scheduler: agent not found for intent=%s, "
                            "skipping target %s=%s",
                            resolved_intent, target_type, target_id,
                        )
                        continue

                    result = await agent.handle(
                        intent=resolved_intent,
                        message=msg,
                        user_id=target_id,
                        db=db,
                        extra_state={"chat_type": target_type},
                    )
                    await self._ws.push_message(
                        target_type=target_type,
                        target_id=target_id,
                        msgtype="markdown",
                        content=result.reply,
                    )
                    logger.info(
                        "Scheduler: pushed to %s=%s, reply=%s",
                        target_type, target_id, result.reply[:100],
                    )
                    await db.commit()
                except Exception as e:
                    logger.exception(
                        "Scheduler: push to %s=%s failed: %s",
                        target_type, target_id, e,
                    )
                    await db.rollback()
