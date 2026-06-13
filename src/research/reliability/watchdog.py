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
        result = {"recovered": 0, "retried": 0}

        # 1. 恢复过期租约
        recovered = await self._steps.recover_expired_leases(db, limit=100)
        for step_id in recovered:
            await self._dispatcher.enqueue_step(step_id)
        result["recovered"] = len(recovered)

        if recovered:
            logger.info("Watchdog: recovered %d expired step(s)", len(recovered))
        return result
