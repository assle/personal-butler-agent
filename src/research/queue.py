"""
研究任务队列适配层
隔离业务服务与 Taskiq，使测试和未来 broker 替换不影响任务服务。
"""
from typing import Protocol


class ResearchDispatcher(Protocol):
    """研究任务派发接口"""

    async def enqueue_planning(self, task_id: str) -> None:
        """派发计划生成任务"""
        raise NotImplementedError

    async def enqueue_step(self, step_id: str) -> None:
        """派发单个研究步骤"""
        raise NotImplementedError

    async def enqueue_research(self, task_id: str) -> None:
        """派发研究执行任务"""
        raise NotImplementedError

    async def enqueue_delivery(self, task_id: str) -> None:
        """派发独立报告投递任务"""
        raise NotImplementedError


class TaskiqResearchDispatcher:
    """通过 Taskiq 派发研究和投递任务"""

    def __init__(self, run_task, deliver_task, *, plan_task=None, step_task=None):
        """注入 Taskiq task 函数

        参数:
            run_task: Phase 1 遗留研究入口 task
            deliver_task: 报告投递 task
            plan_task: 研究规划 task
            step_task: 研究步骤 task
        """
        self._run = run_task
        self._deliver = deliver_task
        self._plan = plan_task
        self._step = step_task

    async def enqueue_planning(self, task_id: str) -> None:
        """派发计划生成任务"""
        if self._plan is not None:
            await self._plan.kiq(task_id)

    async def enqueue_step(self, step_id: str) -> None:
        """派发单个研究步骤"""
        if self._step is not None:
            await self._step.kiq(step_id)

    async def enqueue_delivery(self, task_id: str) -> None:
        """派发独立报告投递任务"""
        await self._deliver.kiq(task_id)

    async def enqueue_research(self, task_id: str) -> None:
        """Phase 1 兼容：派发 legacy 研究任务"""
        await self._run.kiq(task_id)
