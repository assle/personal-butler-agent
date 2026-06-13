"""
研究步骤派发服务
在队列入队前原子认领步骤，入队失败时释放租约
"""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from src.research.steps import ResearchStepService

logger = logging.getLogger(__name__)


class ResearchStepDispatcher:
    """认领就绪步骤并派发到队列"""

    def __init__(self, step_service: ResearchStepService, dispatcher, session_factory, max_concurrent: int = 3):
        """初始化步骤派发器

        参数:
            step_service: 步骤服务实例
            dispatcher: 队列派发器（实现 ResearchDispatcher 协议）
            session_factory: 异步数据库会话工厂
            max_concurrent: 最大并发认领数
        """
        self._steps = step_service
        self._dispatcher = dispatcher
        self._session_factory = session_factory
        self._max = max_concurrent

    async def dispatch_ready(self, task_id: str | None = None) -> int:
        """认领就绪步骤并派发到队列

        先将已到期的 RETRY_WAIT 步骤提升为 READY，
        再原子认领步骤（持久化 running 状态），逐个派发到队列。
        任意步骤入队失败时释放其租约，最后传播首个异常。

        参数:
            task_id: 可选研究任务 ID，不指定时认领所有任务的就绪步骤

        返回:
            int: 成功派发的步骤数
        """
        owner = f"dispatch:{uuid.uuid4().hex[:8]}"
        async with self._session_factory() as db:
            await self._steps.promote_due_retries(db, limit=100)
            steps = await self._steps.claim_next(db, owner=owner, limit=self._max, task_id=task_id)
            await db.commit()

        enqueued = 0
        first_error = None
        for step in steps:
            try:
                await self._dispatcher.enqueue_step(step.id)
                enqueued += 1
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                async with self._session_factory() as db:
                    await self._steps.release_claim(db, step.id, owner=owner)
                    await db.commit()
                logger.warning("Dispatch: released claim for %s after enqueue failure", step.id)

        if first_error is not None:
            raise first_error
        return enqueued
