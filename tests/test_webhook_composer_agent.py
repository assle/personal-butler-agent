"""
群 webhook 内容生成 Agent 测试
验证定时推送只生成最终 markdown 正文，不走私聊或群聊工具。
"""
import pytest


@pytest.mark.asyncio
async def test_webhook_composer_generates_markdown_body(db_session, mock_llm):
    """验证 webhook composer 只返回模型生成的群通知正文"""
    from src.agents.webhook_composer import WebhookComposerAgent

    mock_llm.chat.return_value = "## 早安\n今天记得准时出门。"
    agent = WebhookComposerAgent(llm_client=mock_llm)

    result = await agent.handle(
        "webhook_compose",
        "生成早安提醒",
        "fitness-group",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "fitness-group"},
    )

    assert result.reply == "## 早安\n今天记得准时出门。"
    assert result.data == {"intent": "webhook_compose"}
    mock_llm.chat.assert_awaited_once()
    messages = mock_llm.chat.await_args.kwargs["messages"]
    assert "只生成最终要发到群里的 markdown 正文" in messages[0]["content"]


@pytest.mark.asyncio
async def test_webhook_composer_fallback_on_empty_reply(db_session, mock_llm):
    """验证空回复会降级为安全正文"""
    from src.agents.webhook_composer import WebhookComposerAgent

    mock_llm.chat.return_value = ""
    agent = WebhookComposerAgent(llm_client=mock_llm)

    result = await agent.handle(
        "webhook_compose",
        "提醒大家喝水",
        "group-a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "group-a"},
    )

    assert result.reply == "提醒大家喝水"
