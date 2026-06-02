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


@pytest.fixture
def mock_router():
    """创建 mock IntentRouter，用于自动路由测试"""
    router = AsyncMock()
    router.route.return_value = ("qa", 1.0)
    return router


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
    assert mgr._targets == [("single", "user1", "今日训练建议", "today_plan")]


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


@pytest.mark.asyncio
async def test_scheduler_multi_target_parsing(mock_ws, mock_registry, mock_db_factory):
    """验证多目标 | 分隔解析，单 message 和 intent 广播到所有目标"""
    from src.scheduler import SchedulerManager

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single|single|group",
        target_id="user1|user2|chatid1",
        message="test",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )
    assert mgr._targets == [
        ("single", "user1", "test", "today_plan"),
        ("single", "user2", "test", "today_plan"),
        ("group", "chatid1", "test", "today_plan"),
    ]


@pytest.mark.asyncio
async def test_scheduler_multi_target_count_mismatch(mock_ws, mock_registry, mock_db_factory):
    """验证类型和 ID 数量不匹配时抛出 ValueError"""
    from src.scheduler import SchedulerManager

    with pytest.raises(ValueError, match="数量不匹配"):
        SchedulerManager(
            ws_client=mock_ws,
            agent_registry=mock_registry,
            cron_expression="0 9 * * *",
            target_type="single|single",
            target_id="user1",
            message="test",
            intent="today_plan",
            db_session_factory=mock_db_factory,
        )


@pytest.mark.asyncio
async def test_scheduler_multi_target_empty_id(mock_ws, mock_registry, mock_db_factory):
    """验证空目标 ID 时抛出 ValueError"""
    from src.scheduler import SchedulerManager

    with pytest.raises(ValueError, match="不能为空"):
        SchedulerManager(
            ws_client=mock_ws,
            agent_registry=mock_registry,
            cron_expression="0 9 * * *",
            target_type="",
            target_id="",
            message="test",
            intent="today_plan",
            db_session_factory=mock_db_factory,
        )


@pytest.mark.asyncio
async def test_scheduled_push_multi_target(mock_ws, mock_registry, mock_db_factory):
    """验证多目标推送：对每个目标分别调用 agent.handle 和 push_message"""
    from src.scheduler import SchedulerManager
    from src.schemas.response import AgentResponse
    from unittest.mock import AsyncMock

    mock_agent = AsyncMock()
    mock_agent.handle.return_value = AgentResponse(
        reply="今日训练计划",
        data=None,
    )
    mock_registry.register("today_plan", mock_agent)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single|group",
        target_id="user1|chatid1",
        message="今日训练建议",
        intent="today_plan",
        db_session_factory=mock_db_factory,
    )

    await mgr._scheduled_push()

    # 两次调用 agent.handle
    assert mock_agent.handle.call_count == 2
    # 第一次: single -> user1
    assert mock_agent.handle.call_args_list[0].kwargs["user_id"] == "user1"
    assert mock_agent.handle.call_args_list[0].kwargs["extra_state"] == {"chat_type": "single"}
    # 第二次: group -> chatid1
    assert mock_agent.handle.call_args_list[1].kwargs["user_id"] == "chatid1"
    assert mock_agent.handle.call_args_list[1].kwargs["extra_state"] == {"chat_type": "group"}

    # 两次调用 push_message
    assert mock_ws.push_message.call_count == 2
    mock_ws.push_message.assert_any_call(
        target_type="single", target_id="user1",
        msgtype="markdown", content="今日训练计划",
    )
    mock_ws.push_message.assert_any_call(
        target_type="group", target_id="chatid1",
        msgtype="markdown", content="今日训练计划",
    )


# ── 以下为新测试 ──


@pytest.mark.asyncio
async def test_scheduler_per_target_message(mock_ws, mock_registry, mock_db_factory):
    """验证每个目标可以使用不同的 message 和 intent"""
    from src.scheduler import SchedulerManager
    from src.schemas.response import AgentResponse
    from unittest.mock import AsyncMock

    mock_agent_tp = AsyncMock()
    mock_agent_tp.handle.return_value = AgentResponse(
        reply="训练计划回复",
        data=None,
    )
    mock_agent_mp = AsyncMock()
    mock_agent_mp.handle.return_value = AgentResponse(
        reply="食谱回复",
        data=None,
    )
    mock_registry.register("today_plan", mock_agent_tp)
    mock_registry.register("make_meal_plan", mock_agent_mp)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single|single",
        target_id="user1|user2",
        message="今日训练|今天吃什么",
        intent="today_plan|make_meal_plan",
        db_session_factory=mock_db_factory,
    )

    # 验证 _targets 包含正确的 per-target message 和 intent
    assert mgr._targets == [
        ("single", "user1", "今日训练", "today_plan"),
        ("single", "user2", "今天吃什么", "make_meal_plan"),
    ]

    await mgr._scheduled_push()

    # 第一个目标：today_plan agent 处理 "今日训练"
    assert mock_agent_tp.handle.call_count == 1
    assert mock_agent_tp.handle.call_args.kwargs["message"] == "今日训练"
    assert mock_agent_tp.handle.call_args.kwargs["intent"] == "today_plan"
    assert mock_agent_tp.handle.call_args.kwargs["user_id"] == "user1"

    # 第二个目标：make_meal_plan agent 处理 "今天吃什么"
    assert mock_agent_mp.handle.call_count == 1
    assert mock_agent_mp.handle.call_args.kwargs["message"] == "今天吃什么"
    assert mock_agent_mp.handle.call_args.kwargs["intent"] == "make_meal_plan"
    assert mock_agent_mp.handle.call_args.kwargs["user_id"] == "user2"


@pytest.mark.asyncio
async def test_scheduler_intent_auto_routing(
    mock_ws, mock_registry, mock_db_factory, mock_router,
):
    """验证 intent 为空时自动调用 intent_router.route() 决定意图"""
    from src.scheduler import SchedulerManager
    from src.schemas.response import AgentResponse
    from unittest.mock import AsyncMock

    # 注册 qa agent（mock_router 默认返回 "qa"）
    mock_agent = AsyncMock()
    mock_agent.handle.return_value = AgentResponse(
        reply="自动路由回复",
        data=None,
    )
    mock_registry.register("qa", mock_agent)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single|single",
        target_id="user1|user2",
        message="msg1|msg2",
        intent="",  # 空意图 → 全部自动路由
        db_session_factory=mock_db_factory,
        intent_router=mock_router,
    )

    await mgr._scheduled_push()

    # 验证 intent_router.route() 被每个目标各调用一次
    assert mock_router.route.call_count == 2
    # 第一次用 msg1 路由
    assert mock_router.route.call_args_list[0].args == ("msg1",)
    # 第二次用 msg2 路由
    assert mock_router.route.call_args_list[1].args == ("msg2",)

    # 验证 agent 使用路由结果 "qa" 处理
    assert mock_agent.handle.call_count == 2
    assert mock_agent.handle.call_args_list[0].kwargs["intent"] == "qa"
    assert mock_agent.handle.call_args_list[0].kwargs["message"] == "msg1"
    assert mock_agent.handle.call_args_list[1].kwargs["intent"] == "qa"
    assert mock_agent.handle.call_args_list[1].kwargs["message"] == "msg2"


@pytest.mark.asyncio
async def test_scheduler_message_count_mismatch(mock_ws, mock_registry, mock_db_factory):
    """验证 message 数量（多值）与目标数量不匹配时抛出 ValueError"""
    from src.scheduler import SchedulerManager

    with pytest.raises(ValueError, match="数量不匹配"):
        SchedulerManager(
            ws_client=mock_ws,
            agent_registry=mock_registry,
            cron_expression="0 9 * * *",
            target_type="single|group",
            target_id="user1|chatid1",
            message="msg1|msg2|msg3",  # 3 条消息 vs 2 个目标
            intent="today_plan",
            db_session_factory=mock_db_factory,
        )


@pytest.mark.asyncio
async def test_scheduler_intent_count_mismatch(mock_ws, mock_registry, mock_db_factory):
    """验证 intent 数量（多值）与目标数量不匹配时抛出 ValueError"""
    from src.scheduler import SchedulerManager

    with pytest.raises(ValueError, match="数量不匹配"):
        SchedulerManager(
            ws_client=mock_ws,
            agent_registry=mock_registry,
            cron_expression="0 9 * * *",
            target_type="single|group",
            target_id="user1|chatid1",
            message="test",
            intent="today_plan|make_meal_plan|qa",  # 3 个意图 vs 2 个目标
            db_session_factory=mock_db_factory,
        )


@pytest.mark.asyncio
async def test_scheduler_empty_intent_without_router(mock_ws, mock_registry, mock_db_factory):
    """验证 intent 为空且未提供 intent_router 时，跳过目标不崩溃"""
    from src.scheduler import SchedulerManager

    # 不提供 intent_router
    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single",
        target_id="user1",
        message="test",
        intent="",
        db_session_factory=mock_db_factory,
        # intent_router=None (default)
    )

    await mgr._scheduled_push()
    # 不应崩溃，不应推送
    mock_ws.push_message.assert_not_called()


@pytest.mark.asyncio
async def test_scheduler_mixed_explicit_and_auto_intent(mock_ws, mock_registry, mock_db_factory, mock_router):
    """验证混合 intent：第一个目标走指定 agent，第二个目标走自动路由"""
    from src.scheduler import SchedulerManager
    from src.schemas.response import AgentResponse
    from unittest.mock import AsyncMock

    mock_agent = AsyncMock()
    mock_agent.handle.return_value = AgentResponse(reply="OK", data=None)
    mock_registry.register("today_plan", mock_agent)
    mock_registry.register("qa", mock_agent)

    mgr = SchedulerManager(
        ws_client=mock_ws,
        agent_registry=mock_registry,
        cron_expression="0 9 * * *",
        target_type="single|single",
        target_id="user1|user2",
        message="今天练什么？|今天吃什么？",
        intent="today_plan|",  # 第一个指定，第二个自动路由
        db_session_factory=mock_db_factory,
        intent_router=mock_router,
    )

    await mgr._scheduled_push()

    # intent_router 只对第二个目标调用（第一个 intent 已有值）
    mock_router.route.assert_called_once_with("今天吃什么？")

    assert mock_agent.handle.call_count == 2
    # 第一个：直接使用 today_plan
    assert mock_agent.handle.call_args_list[0].kwargs["intent"] == "today_plan"
    # 第二个：router 返回 "qa"
    assert mock_agent.handle.call_args_list[1].kwargs["intent"] == "qa"

    assert mock_ws.push_message.call_count == 2
