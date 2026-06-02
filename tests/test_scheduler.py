"""
调度器测试
测试 SchedulerManager 的创建、job 触发和推送逻辑
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_ws():
    """创建 mock WebSocket 客户端"""
    ws = AsyncMock()
    ws.push_message.return_value = True
    return ws


@pytest.fixture
def mock_registry():
    """创建 mock AgentRegistry"""
    from src.agents.registry import AgentRegistry
    registry = AgentRegistry()
    return registry


@pytest.fixture
def mock_db_factory():
    """创建 mock 数据库会话工厂"""
    from unittest.mock import AsyncMock, MagicMock
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock()
    factory.return_value = session
    return factory


@pytest.mark.asyncio
async def test_scheduler_creation(mock_ws, mock_registry, mock_db_factory):
    """验证 SchedulerManager 创建不报错"""
    from src.scheduler import SchedulerManager

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="今日训练建议",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )
    assert mgr._cron == "0 9 * * *"
    assert mgr._target_type == "single"
    assert mgr._target_id == "user1"


@pytest.mark.asyncio
async def test_scheduled_push_calls_agent_and_pushes(mock_ws, mock_registry, mock_db_factory):
    """验证 _scheduled_push 调用 agent 并推送结果"""
    from src.scheduler import SchedulerManager
    from src.schemas.response import AgentResponse
    from unittest.mock import AsyncMock

    # 注册一个 mock agent
    mock_agent = AsyncMock()
    mock_agent.handle.return_value = AgentResponse(
        reply="今日训练计划：练肩 + 哑铃推举",
        data=None,
    )
    mock_registry.register("today_plan", mock_agent)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="今日训练建议",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )

    await mgr._scheduled_push()

    # 验证 agent.handle 被调用
    mock_agent.handle.assert_called_once()
    call_kwargs = mock_agent.handle.call_args.kwargs
    assert call_kwargs["intent"] == "today_plan"
    assert call_kwargs["message"] == "今日训练建议"
    assert call_kwargs["user_id"] == "user1"

    # 验证 ws.push_message 被调用
    mock_ws.push_message.assert_called_once_with(
        target_type="single",
        target_id="user1",
        msgtype="markdown",
        content="今日训练计划：练肩 + 哑铃推举",
    )


@pytest.mark.asyncio
async def test_scheduled_push_handles_agent_not_found(mock_ws, mock_registry, mock_db_factory):
    """验证 agent 未注册时不崩溃"""
    from src.scheduler import SchedulerManager

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="test",
        intent="nonexistent",
        db_session_factory=mock_db_factory,
    )

    await mgr._scheduled_push()
    # 不应抛出异常，且不应调用 push_message
    mock_ws.push_message.assert_not_called()


@pytest.mark.asyncio
async def test_scheduled_push_handles_agent_error(mock_ws, mock_registry, mock_db_factory):
    """验证 agent 处理异常时不崩溃"""
    from src.scheduler import SchedulerManager
    from unittest.mock import AsyncMock

    mock_agent = AsyncMock()
    mock_agent.handle.side_effect = Exception("LLM error")
    mock_registry.register("today_plan", mock_agent)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="test",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )

    await mgr._scheduled_push()
    # 不应抛出异常，但 push_message 不应被调用
    mock_ws.push_message.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_start_and_shutdown(mock_ws, mock_registry, mock_db_factory):
    """验证调度器启动和关闭不报错"""
    from src.scheduler import SchedulerManager

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="test",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )
    mgr.start()
    mgr.shutdown()
