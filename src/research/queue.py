"""
研究任务队列适配层
隔离业务服务与 Taskiq，使测试和未来 broker 替换不影响任务服务。
"""
from typing import Protocol


class ResearchDispatcher(Protocol):
    """研究任务派发接口"""

    async def enqueue_research(self, task_id: str) -> None:
        """派发研究执行任务"""
        raise NotImplementedError

    async def enqueue_delivery(self, task_id: str) -> None:
        """派发独立报告投递任务"""
        raise NotImplementedError


class TaskiqResearchDispatcher:
    """Taskiq 派发实现"""

    def __init__(self, research_task, delivery_task):
        """注入已注册的 Taskiq task 对象"""
        self._research_task = research_task
        self._delivery_task = delivery_task

    async def enqueue_research(self, task_id: str) -> None:
        """把任务 ID 放入研究队列"""
        await self._research_task.kiq(task_id)

    async def enqueue_delivery(self, task_id: str) -> None:
        """把任务 ID 放入独立投递任务"""
        await self._delivery_task.kiq(task_id)
