"""
Hook 总线
提供类型化的研究生命周期事件 Hook 注册和执行基础设施

Workflow:
1. 应用启动时注册 Hook（如审批检查、成本控制、审计日志）
2. 研究任务执行过程中在关键节点 emit 事件
3. 关键 Hook 失败抛出 CriticalHookError 阻止继续执行
4. 非关键 Hook 失败记录日志但不影响主流程
"""
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from enum import StrEnum

logger = logging.getLogger(__name__)


class HookEvent(StrEnum):
    """研究生命周期 Hook 事件"""

    BEFORE_RESEARCH = "before_research"
    AFTER_PLAN = "after_plan"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    ON_ERROR = "on_error"
    BEFORE_DELIVERY = "before_delivery"
    AFTER_RESEARCH = "after_research"


class CriticalHookError(RuntimeError):
    """关键 Hook 执行失败，阻止操作继续"""


HookFn = Callable[[dict], Awaitable[None]]
"""Hook 函数签名：接收上下文字典，异步执行"""


class HookBus:
    """按注册顺序管理并执行类型化 Hook"""

    def __init__(self):
        """初始化 Hook 总线

        参数:
            无
        """
        self._hooks: dict[HookEvent, list[tuple[HookFn, bool]]] = defaultdict(list)

    def register(
        self,
        event: HookEvent,
        fn: HookFn,
        *,
        critical: bool = False,
    ) -> None:
        """为指定事件注册 Hook

        参数:
            event: 要监听的生命周期事件
            fn: 异步回调函数
            critical: 为 True 时 Hook 失败会阻止操作继续
        """
        self._hooks[event].append((fn, critical))

    async def emit(self, event: HookEvent, context: dict) -> None:
        """触发指定事件的所有已注册 Hook

        参数:
            event: 要触发的事件
            context: 传递给每个 Hook 的上下文字典

        异常:
            CriticalHookError: 当一个关键 Hook 抛出异常时
        """
        for fn, critical in self._hooks[event]:
            try:
                await fn(context)
            except Exception as exc:
                if critical:
                    raise CriticalHookError(
                        f"关键 Hook {event.value} 执行失败: {exc}"
                    ) from exc
                logger.warning(
                    "非关键 Hook %s 执行失败: %s",
                    event.value,
                    exc,
                )
