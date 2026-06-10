"""
调度器测试
验证 APScheduler 企业微信群 webhook 推送只调用 WebhookComposerAgent 生成正文。
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_db_factory():
    """创建 mock 数据库会话工厂

    返回:
        MagicMock: 返回异步上下文数据库会话的工厂
    """
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock()
    factory.return_value = session
    return factory


@pytest.fixture
def mock_composer_agent():
    """创建 mock WebhookComposerAgent

    返回:
        AsyncMock: handle() 固定返回 markdown 正文
    """
    from src.schemas.response import AgentResponse

    agent = AsyncMock()
    agent.handle.return_value = AgentResponse(
        reply="## 早安\n今天记得准时出门。",
        data={"intent": "webhook_compose"},
    )
    return agent


@pytest.fixture
def mock_webhook_client():
    """创建 mock webhook 推送客户端

    返回:
        AsyncMock: send_markdown() 固定成功
    """
    client = AsyncMock()
    client.send_markdown.return_value = True
    return client


def test_load_webhook_targets_reads_json(tmp_path):
    """验证 JSON 文件会转换为 webhook target 列表"""
    from src.scheduler import load_webhook_targets

    config_path = tmp_path / "targets.json"
    config_path.write_text(
        json.dumps(
            [
                {
                    "name": "work",
                    "cron": "0 9 * * *",
                    "webhook_url": "https://example.test/webhook",
                    "message": "生成早安提醒",
                    "chat_id": "chat-1",
                    "enabled": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    targets = load_webhook_targets(str(config_path))

    assert len(targets) == 1
    assert targets[0].name == "work"
    assert targets[0].cron == "0 9 * * *"
    assert targets[0].message == "生成早安提醒"
    assert targets[0].chat_id == "chat-1"
    assert targets[0].enabled is True


def test_load_webhook_targets_rejects_duplicate_names(tmp_path):
    """验证重复 target name 会被拒绝"""
    from src.scheduler import load_webhook_targets

    config_path = tmp_path / "targets.json"
    config_path.write_text(
        json.dumps(
            [
                {
                    "name": "work",
                    "cron": "0 9 * * *",
                    "webhook_url": "https://example.test/a",
                    "message": "A",
                },
                {
                    "name": "work",
                    "cron": "0 10 * * *",
                    "webhook_url": "https://example.test/b",
                    "message": "B",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="name 重复"):
        load_webhook_targets(str(config_path))


def test_scheduler_creation_uses_webhook_targets(
    mock_db_factory,
    mock_composer_agent,
    mock_webhook_client,
):
    """验证 SchedulerManager 只保存 webhook composer 依赖和 targets"""
    from src.scheduler import SchedulerManager, WebhookSchedulerTarget

    target = WebhookSchedulerTarget(
        name="work",
        cron="0 9 * * *",
        webhook_url="https://example.test/webhook",
        message="生成早安提醒",
    )
    mgr = SchedulerManager(
        db_session_factory=mock_db_factory,
        webhook_composer_agent=mock_composer_agent,
        webhook_client=mock_webhook_client,
        webhook_targets=[target],
    )

    assert mgr._webhook_composer_agent is mock_composer_agent
    assert mgr._webhook_targets == [target]


@pytest.mark.asyncio
async def test_scheduled_webhook_push_calls_composer_and_pushes(
    mock_db_factory,
    mock_composer_agent,
    mock_webhook_client,
):
    """验证 webhook job 调用 composer agent 后发送 markdown"""
    from src.scheduler import SchedulerManager, WebhookSchedulerTarget

    target = WebhookSchedulerTarget(
        name="work",
        cron="0 9 * * *",
        webhook_url="https://example.test/webhook",
        message="生成早安提醒",
        chat_id="chat-1",
    )
    mgr = SchedulerManager(
        db_session_factory=mock_db_factory,
        webhook_composer_agent=mock_composer_agent,
        webhook_client=mock_webhook_client,
        webhook_targets=[target],
    )

    await mgr._scheduled_webhook_push(target)
    db_session = mock_db_factory.return_value.__aenter__.return_value

    mock_composer_agent.handle.assert_awaited_once_with(
        intent="webhook_compose",
        message=target.message,
        user_id="chat-1",
        db=db_session,
        extra_state={"chat_type": "group", "chat_id": "chat-1"},
    )
    mock_webhook_client.send_markdown.assert_awaited_once_with(
        "https://example.test/webhook",
        "## 早安\n今天记得准时出门。",
    )
    db_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduled_webhook_push_uses_name_when_chat_id_missing(
    mock_db_factory,
    mock_composer_agent,
    mock_webhook_client,
):
    """验证 chat_id 为空时使用 target name 作为群上下文"""
    from src.scheduler import SchedulerManager, WebhookSchedulerTarget

    target = WebhookSchedulerTarget(
        name="fitness-group",
        cron="0 9 * * *",
        webhook_url="https://example.test/webhook",
        message="提醒大家喝水",
    )
    mgr = SchedulerManager(
        db_session_factory=mock_db_factory,
        webhook_composer_agent=mock_composer_agent,
        webhook_client=mock_webhook_client,
        webhook_targets=[target],
    )

    await mgr._scheduled_webhook_push(target)

    assert mock_composer_agent.handle.await_args.kwargs["user_id"] == "fitness-group"
    assert mock_composer_agent.handle.await_args.kwargs["extra_state"] == {
        "chat_type": "group",
        "chat_id": "fitness-group",
    }


@pytest.mark.asyncio
async def test_scheduled_webhook_push_skips_without_composer(
    mock_db_factory,
    mock_webhook_client,
):
    """验证缺少 composer agent 时不发送 webhook"""
    from src.scheduler import SchedulerManager, WebhookSchedulerTarget

    target = WebhookSchedulerTarget(
        name="work",
        cron="0 9 * * *",
        webhook_url="https://example.test/webhook",
        message="生成早安提醒",
    )
    mgr = SchedulerManager(
        db_session_factory=mock_db_factory,
        webhook_composer_agent=None,
        webhook_client=mock_webhook_client,
        webhook_targets=[target],
    )

    await mgr._scheduled_webhook_push(target)

    mock_webhook_client.send_markdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_webhook_push_rolls_back_when_send_fails(
    mock_db_factory,
    mock_composer_agent,
    mock_webhook_client,
):
    """验证 webhook 发送失败时回滚数据库会话"""
    from src.scheduler import SchedulerManager, WebhookSchedulerTarget

    mock_webhook_client.send_markdown.return_value = False
    target = WebhookSchedulerTarget(
        name="work",
        cron="0 9 * * *",
        webhook_url="https://example.test/webhook",
        message="生成早安提醒",
    )
    mgr = SchedulerManager(
        db_session_factory=mock_db_factory,
        webhook_composer_agent=mock_composer_agent,
        webhook_client=mock_webhook_client,
        webhook_targets=[target],
    )

    await mgr._scheduled_webhook_push(target)
    db_session = mock_db_factory.return_value.__aenter__.return_value

    db_session.rollback.assert_awaited_once()
    db_session.commit.assert_not_awaited()


def test_scheduler_start_registers_enabled_webhook_targets(
    monkeypatch,
    mock_db_factory,
    mock_composer_agent,
    mock_webhook_client,
):
    """验证 start() 只为启用的 webhook target 注册 job"""
    from src.scheduler import SchedulerManager, WebhookSchedulerTarget

    fake_scheduler = MagicMock()
    monkeypatch.setattr(
        "src.scheduler.manager.AsyncIOScheduler",
        MagicMock(return_value=fake_scheduler),
    )
    targets = [
        WebhookSchedulerTarget(
            name="enabled",
            cron="0 9 * * *",
            webhook_url="https://example.test/a",
            message="A",
            enabled=True,
        ),
        WebhookSchedulerTarget(
            name="disabled",
            cron="0 10 * * *",
            webhook_url="https://example.test/b",
            message="B",
            enabled=False,
        ),
    ]
    mgr = SchedulerManager(
        db_session_factory=mock_db_factory,
        webhook_composer_agent=mock_composer_agent,
        webhook_client=mock_webhook_client,
        webhook_targets=targets,
    )

    mgr.start()

    fake_scheduler.add_job.assert_called_once()
    assert fake_scheduler.add_job.call_args.kwargs["id"] == "scheduled_webhook_push:enabled"
    fake_scheduler.start.assert_called_once()
