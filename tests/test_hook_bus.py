"""
Hook 总线测试
验证 HookBus 按注册顺序执行 Hook，以及关键 Hook 的失败关闭行为
"""
import pytest

from src.governance.hooks import (
    CriticalHookError,
    HookBus,
    HookEvent,
)


async def _record(calls, name):
    """辅助函数：在调用列表中记录名称"""
    calls.append(name)


async def _failing_hook(ctx):
    """辅助函数：始终抛出异常的 Hook"""
    raise RuntimeError("hook failed")


@pytest.mark.asyncio
async def test_hook_bus_runs_hooks_in_registration_order():
    """验证同一事件的 Hook 按注册顺序执行"""
    calls = []
    bus = HookBus()
    bus.register(HookEvent.BEFORE_RESEARCH, lambda ctx: _record(calls, "a"))
    bus.register(HookEvent.BEFORE_RESEARCH, lambda ctx: _record(calls, "b"))
    await bus.emit(HookEvent.BEFORE_RESEARCH, {"task_id": "R1"})
    assert calls == ["a", "b"]


@pytest.mark.asyncio
async def test_critical_hook_failure_is_fail_closed():
    """验证权限类 Hook 失败时阻止继续执行"""
    bus = HookBus()
    bus.register(HookEvent.BEFORE_TOOL, _failing_hook, critical=True)
    with pytest.raises(CriticalHookError):
        await bus.emit(HookEvent.BEFORE_TOOL, {"tool": "web.search"})


@pytest.mark.asyncio
async def test_non_critical_hook_failure_is_logged_only():
    """验证非关键 Hook 失败时不阻止继续执行"""
    bus = HookBus()
    bus.register(HookEvent.BEFORE_RESEARCH, _failing_hook, critical=False)
    # 不应抛出异常
    await bus.emit(HookEvent.BEFORE_RESEARCH, {"task_id": "R2"})


@pytest.mark.asyncio
async def test_hook_bus_emit_with_no_registrations():
    """验证无注册 Hook 时 emit 不报错"""
    bus = HookBus()
    await bus.emit(HookEvent.ON_ERROR, {"task_id": "R3"})


@pytest.mark.asyncio
async def test_multiple_events_are_independent():
    """验证不同事件的 Hook 互不影响"""
    before_calls = []
    after_calls = []
    bus = HookBus()
    bus.register(HookEvent.BEFORE_RESEARCH, lambda ctx: _record(before_calls, "before"))
    bus.register(HookEvent.AFTER_RESEARCH, lambda ctx: _record(after_calls, "after"))
    await bus.emit(HookEvent.BEFORE_RESEARCH, {"task_id": "R4"})
    assert before_calls == ["before"]
    assert after_calls == []
