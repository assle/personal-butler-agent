"""
研究全链路追踪
提供 TraceContext 数据类和 StageRecorder 阶段测量记录器。

Workflow:
1. TraceContext 在链路起点创建，携带 trace_id 跨步骤传播
2. StageRecorder 通过 async context manager 包裹阶段执行
3. 阶段开始/完成/失败时向 ResearchEvent 追加对应事件
"""
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.research.events import EventWriter


@dataclass(frozen=True)
class TraceContext:
    """全链路追踪上下文"""

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    workspace_id: str = ""
    task_id: str = ""
    step_id: str | None = None
    attempt: int | None = None

    def as_log_fields(self) -> dict:
        """返回日志字段字典

        返回:
            dict: 含 trace_id、workspace_id、task_id、step_id、attempt
        """
        return {
            "trace_id": self.trace_id,
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "attempt": self.attempt,
        }


class StageRecorder:
    """阶段测量记录器：记录开始、完成和失败事件及耗时"""

    def __init__(self, events: EventWriter, task_service):
        """初始化记录器

        参数:
            events: 事件写入器
            task_service: 任务服务（用于获取任务 trace_id）
        """
        self._events = events
        self._tasks = task_service

    @asynccontextmanager
    async def measure(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        workspace_id: str,
        stage: str,
        step_id: str | None = None,
        attempt: int | None = None,
    ):
        """测量阶段执行时长并记录事件

        用法:
            async with recorder.measure(db, task_id="R1", workspace_id="ws-a", stage="planning"):
                ...

        参数:
            db: 异步数据库会话
            task_id: 研究任务 ID
            workspace_id: 工作空间 ID
            stage: 阶段名称（如 planning、execution、synthesis）
            step_id: 可选步骤 ID
            attempt: 可选重试次数
        """
        from src.research.reliability.errors import classify_error

        trace = await self._tasks.get_task(db, task_id)
        started = time.perf_counter()
        await self._events.append(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            step_id=step_id,
            event_type="stage.started",
            payload={
                "stage": stage,
                "trace_id": trace.trace_id,
                "attempt": attempt,
            },
            trace_id=trace.trace_id,
        )
        try:
            yield
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            cat = classify_error(exc).category.value
            await self._events.append(
                db,
                workspace_id=workspace_id,
                task_id=task_id,
                step_id=step_id,
                event_type="stage.failed",
                payload={
                    "stage": stage,
                    "elapsed_ms": elapsed,
                    "failure_category": cat,
                    "trace_id": trace.trace_id,
                    "attempt": attempt,
                },
                trace_id=trace.trace_id,
            )
            raise
        else:
            elapsed = int((time.perf_counter() - started) * 1000)
            await self._events.append(
                db,
                workspace_id=workspace_id,
                task_id=task_id,
                step_id=step_id,
                event_type="stage.completed",
                payload={
                    "stage": stage,
                    "elapsed_ms": elapsed,
                    "trace_id": trace.trace_id,
                    "attempt": attempt,
                },
                trace_id=trace.trace_id,
            )
