"""研究工具注册表"""
import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.research.tools.schemas import (
    ResearchToolDefinition,
    ToolExecutionContext,
    ToolExecutionResult,
)

logger = logging.getLogger(__name__)


class DuplicateResearchToolError(ValueError):
    """重复注册研究工具"""


class ResearchToolDeniedError(RuntimeError):
    """工具执行被权限引擎拒绝"""


class ResearchToolRegistry:
    """按名称注册、校验和路由研究工具"""

    def __init__(self, permission_engine: Any = None, hook_bus: Any = None, circuit_breaker: Any = None):
        """初始化工具注册表

        参数:
            permission_engine: 可选权限引擎
            hook_bus: 可选 Hook 总线
            circuit_breaker: 可选提供者熔断器
        """
        self._tools: dict[str, ResearchToolDefinition] = {}
        self._providers: dict[str, Any] = {}
        self._permission = permission_engine
        self._hooks = hook_bus
        self._circuit = circuit_breaker

    def register(
        self,
        definition: ResearchToolDefinition,
        provider: Any = None,
    ) -> None:
        """注册研究工具

        参数:
            definition: 工具定义
            provider: 可选的工具提供者

        异常:
            DuplicateResearchToolError: 工具名已存在
        """
        if definition.name in self._tools:
            raise DuplicateResearchToolError(
                f"研究工具 {definition.name} 已注册"
            )
        self._tools[definition.name] = definition
        if provider is not None:
            self._providers[definition.name] = provider

    def get_definition(self, name: str) -> ResearchToolDefinition | None:
        """获取工具定义"""
        return self._tools.get(name)

    def has_provider(self, name: str) -> bool:
        """返回指定工具是否绑定可执行提供者"""
        return name in self._providers

    def list_tools(self) -> list[ResearchToolDefinition]:
        """列出所有已注册工具"""
        return list(self._tools.values())

    async def execute(
        self,
        db: AsyncSession,
        context: ToolExecutionContext,
        tool_name: str,
        arguments: dict,
    ) -> ToolExecutionResult:
        """执行注册工具

        参数:
            db: 异步数据库会话
            context: 执行上下文
            tool_name: 工具名
            arguments: 工具参数

        返回:
            ToolExecutionResult
        """
        definition = self._tools.get(tool_name)
        if definition is None:
            return ToolExecutionResult(
                success=False,
                error=f"未注册的研究工具: {tool_name}",
            )

        # 发射 BEFORE_TOOL Hook
        if self._hooks is not None:
            from src.governance.hooks import CriticalHookError, HookEvent
            try:
                await self._hooks.emit(
                    HookEvent.BEFORE_TOOL,
                    {
                        "tool": tool_name,
                        "workspace_id": context.workspace_id,
                        "task_id": context.task_id,
                    },
                )
            except CriticalHookError:
                raise ResearchToolDeniedError(
                    f"工具 {tool_name} 被 Hook 拒绝"
                )

        # 权限检查
        if self._permission is not None:
            from src.governance.permissions import (
                PermissionEffect,
                PermissionRequest,
            )
            decision = self._permission.evaluate(
                PermissionRequest(
                    operation=f"tool.{tool_name}",
                    role="member",
                    risk_level=definition.risk_level,
                    cost_class=definition.cost_class,
                    # 工具执行仅在计划级审批通过后发生，首次使用检查在计划级完成
                    research_approved_once=True,
                    workspace_matches=True,
                )
            )
            if decision.effect != PermissionEffect.ALLOW:
                return ToolExecutionResult(
                    success=False,
                    error=f"工具 {tool_name} 权限不足: {decision.reason}",
                )

        # 提供者熔断检查
        provider_name = definition.provider_name or tool_name
        if self._circuit is not None and not await self._circuit.allow(provider_name):
            return ToolExecutionResult(
                success=False,
                error=f"provider_circuit_open: {provider_name}",
                data={"failure_category": "provider_5xx", "retryable": True},
            )

        # 执行提供者
        provider = self._providers.get(tool_name)
        if provider is None:
            return ToolExecutionResult(
                success=False,
                error=f"工具 {tool_name} 无可用提供者",
            )

        try:
            async with asyncio.timeout(definition.timeout_seconds):
                result = await provider.execute(db, context, arguments)
        except asyncio.TimeoutError:
            return ToolExecutionResult(
                success=False,
                error=f"工具 {tool_name} 执行超时 ({definition.timeout_seconds}s)",
            )
        except Exception as exc:
            if self._circuit is not None:
                await self._circuit.record_failure(provider_name)
            from src.research.reliability.errors import classify_error, FailureCategory
            decision = classify_error(exc)
            if decision.degrade_provider:
                logger.warning("Registry: provider degraded for %s", tool_name)
            return ToolExecutionResult(
                success=False,
                error=f"{decision.category.value}: {exc}",
                data={"failure_category": decision.category.value, "retryable": decision.retryable},
            )

        # 记录成功并发射 AFTER_TOOL Hook
        if self._circuit is not None and result.success:
            await self._circuit.record_success(provider_name)
        if self._hooks is not None:
            from src.governance.hooks import HookEvent
            try:
                await self._hooks.emit(
                    HookEvent.AFTER_TOOL,
                    {"tool": tool_name, "success": result.success},
                )
            except Exception:
                pass

        return result
