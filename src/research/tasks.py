"""
Taskiq 研究与投递任务
Taskiq wrapper 只接收 task_id；数据库会话和服务在 Worker 进程内重新创建。
"""
import asyncio

from redis.asyncio import Redis

from src.config import settings
from src.db.session import async_session
from src.llm.client import LLMClient
from src.research.broker import broker
from src.research.delivery import ResearchDeliveryService
from src.research.executor import FoundationResearchExecutor
from src.research.queue import TaskiqResearchDispatcher
from src.research.service import ResearchTaskService
from src.wechat.app_client import (
    RedisAccessTokenCache,
    WeComAppMessageClient,
)


async def execute_research_job(
    task_id: str,
    *,
    session_factory,
    executor,
    dispatcher,
    task_service,
    timeout_seconds,
) -> None:
    """执行研究、提交报告，再派发独立投递任务"""
    async with session_factory() as db:
        try:
            async with asyncio.timeout(timeout_seconds):
                await executor.execute(db, task_id)
            await db.commit()
        except TimeoutError:
            await db.rollback()
            async with session_factory() as timeout_db:
                await task_service.mark_timed_out(
                    timeout_db,
                    task_id,
                    f"research exceeded {timeout_seconds} seconds",
                )
                await timeout_db.commit()
            raise
        except Exception as exc:
            await db.rollback()
            async with session_factory() as failed_db:
                await task_service.mark_failed(failed_db, task_id, str(exc))
                await failed_db.commit()
            raise
    await dispatcher.enqueue_delivery(task_id)


async def execute_delivery_job(
    task_id: str,
    *,
    session_factory,
    delivery_service,
    sleep=asyncio.sleep,
) -> None:
    """独立投递，指数退避重试三次"""
    last_error: Exception | None = None
    for attempt, delay in enumerate((0, 1, 2), start=1):
        if delay:
            await sleep(delay)
        async with session_factory() as db:
            try:
                await delivery_service.deliver(db, task_id)
                await db.commit()
                return
            except Exception as exc:
                last_error = exc
                await db.commit()
    assert last_error is not None
    raise last_error


_task_service = ResearchTaskService(
    max_rounds=settings.research_max_rounds,
    timeout_seconds=settings.research_timeout_seconds,
)
_redis_client = Redis.from_url(settings.redis_url)
_app_client = WeComAppMessageClient(
    corp_id=settings.wecom_app_corp_id,
    secret=settings.wecom_app_secret,
    agent_id=settings.wecom_app_agent_id,
    cache=RedisAccessTokenCache(_redis_client),
)
_executor = FoundationResearchExecutor(_task_service, LLMClient())
_delivery_service = ResearchDeliveryService(_task_service, _app_client)


@broker.task(task_name="research.deliver")
async def deliver_research_task(task_id: str) -> None:
    """Taskiq 报告投递入口"""
    await execute_delivery_job(
        task_id,
        session_factory=async_session,
        delivery_service=_delivery_service,
    )


@broker.task(task_name="research.run")
async def run_research_task(task_id: str) -> None:
    """Taskiq 研究执行入口"""
    dispatcher = TaskiqResearchDispatcher(
        run_research_task, deliver_research_task
    )
    await execute_research_job(
        task_id,
        session_factory=async_session,
        executor=_executor,
        dispatcher=dispatcher,
        task_service=_task_service,
        timeout_seconds=settings.research_timeout_seconds,
    )
