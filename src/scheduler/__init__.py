"""
APScheduler 定时调度管理器
管理定时任务的启动、停止和 job 注册

Workflow:
  1. SchedulerManager.start() 启动 AsyncIOScheduler
  2. URL 回调模式下可按 JSON 配置为多个群 webhook 注册独立 cron job
  3. 到点触发 ButlerAgent/领域 agent 管线，生成 markdown 后推送到群 webhook
  4. 旧 WebSocket 主动推送接口保留兼容，但 main.py 不再默认启动
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

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
    # 到点时交给 agent 的触发消息
    message: str
    # agent intent；默认走 ButlerAgent 总控
    intent: str = "butler"
    # 可选群上下文 ID；为空时使用 name
    chat_id: str | None = None
    # 是否启用该目标；配置中可临时关闭单个群
    enabled: bool = True


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

    async def send_markdown(self, webhook_url: str, content: str) -> bool:
        """发送 markdown 消息到企业微信群 webhook

        参数:
            webhook_url: 企业微信群机器人 webhook 地址
            content: 要发送的 markdown 内容

        返回:
            bool: 发送成功返回 True，否则返回 False
        """
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
        cron = str(item.get("cron", "")).strip()
        webhook_url = str(item.get("webhook_url", "")).strip()
        message = str(item.get("message", "")).strip()
        intent = str(item.get("intent", "butler")).strip() or "butler"
        chat_id = str(item.get("chat_id", "")).strip() or None
        enabled = bool(item.get("enabled", True))
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
                cron=cron,
                webhook_url=webhook_url,
                message=message,
                intent=intent,
                chat_id=chat_id,
                enabled=enabled,
            )
        )
    return targets


class SchedulerManager:
    """定时调度管理器，封装 APScheduler 的生命周期"""

    def __init__(
        self,
        ws_client=None,
        agent_registry=None,
        cron_expression: str = "",
        target_type: str = "",
        target_id: str = "",
        message: str = "",
        intent: str = "",
        db_session_factory=None,
        intent_router=None,
        butler_agent=None,
        webhook_client: WebhookPushClient | None = None,
        webhook_targets: list[WebhookSchedulerTarget] | None = None,
    ):
        """初始化调度管理器

        参数:
            ws_client: WeComWSClient 实例，用于旧主动推送兼容
            agent_registry: AgentRegistry 实例
            cron_expression: cron 表达式（如 "0 9 * * *"）
            target_type: 推送目标类型，| 分隔多个值（如 "single|group"）
            target_id: 推送目标 ID，| 分隔多个值（如 "user1|chatid1"）
            message: 发给 agent 的触发消息，| 分隔多值（单值广播，多值需与目标数匹配）
            intent: agent intent 标识，| 分隔多值（空字符串表示自动路由）
            db_session_factory: 异步数据库会话工厂
            intent_router: IntentRouter 实例，当 intent 为空时自动路由（可选，默认 None）
            butler_agent: ButlerAgent 实例，用于 webhook 主动推送生成内容
            webhook_client: 企业微信群 webhook 推送客户端
            webhook_targets: 多群 webhook 定时目标列表；提供时启用新推送模式
        """
        self._ws = ws_client
        self._agent_registry = agent_registry
        self._cron = cron_expression
        self._db_session_factory = db_session_factory
        self._intent_router = intent_router
        self._butler_agent = butler_agent
        self._webhook_client = webhook_client
        self._webhook_targets = webhook_targets or []
        self._scheduler = AsyncIOScheduler()
        self._targets: list[tuple[str, str, str, str]] = []

        if self._webhook_targets:
            return

        # 解析 | 分隔的多目标配置，按位置配对
        types = [t.strip() for t in target_type.split("|") if t.strip()]
        ids = [i.strip() for i in target_id.split("|") if i.strip()]
        if len(types) != len(ids):
            raise ValueError(
                f"target_type 与 target_id 数量不匹配: "
                f"{len(types)} 个类型 vs {len(ids)} 个 ID"
            )
        if not types:
            raise ValueError("target_id 不能为空")

        # 解析消息配置（| 分隔，单值广播，多值需与目标数匹配）
        messages_raw = [m.strip() for m in message.split("|")]
        if len(messages_raw) == 1:
            messages = messages_raw * len(types)
        else:
            if len(messages_raw) != len(types):
                raise ValueError(
                    f"message 与 target_id 数量不匹配: "
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
                    f"intent 与 target_id 数量不匹配: "
                    f"{len(intents_raw)} 个意图 vs {len(types)} 个目标"
                )
            intents = intents_raw

        # 每个目标: (类型, ID, 消息, 意图)
        self._targets = list(zip(types, ids, messages, intents))

    def start(self):
        """启动调度器，注册定时任务

        参数:
            无

        返回:
            None
        """
        if self._webhook_targets:
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
            self._scheduler.start()
            logger.info(
                "Scheduler webhook: started, enabled_targets=%s",
                [target.name for target in self._webhook_targets if target.enabled],
            )
            return

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
        """关闭调度器

        参数:
            无

        返回:
            None
        """
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler: shutdown")

    def _agent_for_intent(self, intent: str):
        """根据 intent 获取 agent 实例

        参数:
            intent: agent intent 标识，"butler" 优先返回 ButlerAgent

        返回:
            object | None: 可处理该 intent 的 agent，未找到时返回 None
        """
        if intent == "butler" and self._butler_agent is not None:
            return self._butler_agent
        if self._agent_registry is None:
            return None
        return self._agent_registry.get(intent)

    async def _resolve_intent(self, message: str, configured_intent: str) -> str:
        """解析定时目标的最终 intent

        参数:
            message: 触发消息
            configured_intent: 配置中的 intent，可为空

        返回:
            str: 最终 intent；无法自动路由时返回空字符串
        """
        resolved_intent = configured_intent
        if not resolved_intent and self._intent_router is not None:
            resolved_intent, _ = await self._intent_router.route(message)
            logger.info(
                "Scheduler: auto-routed intent=%s for msg=%s",
                resolved_intent, message[:50],
            )
        return resolved_intent

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
        async with self._db_session_factory() as db:
            try:
                resolved_intent = await self._resolve_intent(
                    target.message,
                    target.intent,
                )
                agent = self._agent_for_intent(resolved_intent)
                if agent is None:
                    logger.error(
                        "Scheduler webhook: agent not found for intent=%s, "
                        "skipping target name=%s",
                        resolved_intent,
                        target.name,
                    )
                    return

                chat_id = target.chat_id or target.name
                result = await agent.handle(
                    intent=resolved_intent,
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
                    resolved_intent = await self._resolve_intent(msg, intent)

                    agent = self._agent_for_intent(resolved_intent)
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
