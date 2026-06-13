"""研究步骤看门狗"""
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ResearchWatchdog:
    def __init__(self, step_service, dispatcher, task_service):
        self._steps = step_service
        self._dispatcher = dispatcher
        self._tasks = task_service

    async def run_once(self, db: AsyncSession) -> dict:
        result = {"recovered": 0, "retried": 0, "dispatched": 0}

        # 1. 恢复过期租约
        recovered = await self._steps.recover_expired_leases(db, limit=100)
        # 2. 提升到期重试步骤
        promoted = await self._steps.promote_due_retries(db, limit=100)

        if recovered or promoted:
            await db.commit()
            # 通过 dispatcher 认领后再入队，避免重复入队
            dispatched = await self._dispatcher.dispatch_ready()
            result.update(recovered=len(recovered), retried=promoted, dispatched=dispatched)
        else:
            result.update(recovered=len(recovered), retried=promoted)

        if recovered:
            logger.info("Watchdog: recovered %d expired step(s), promoted %d retries",
                        len(recovered), promoted)
        return result
