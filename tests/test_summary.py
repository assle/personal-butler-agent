import pytest


@pytest.fixture
def summary_agent(mock_llm):
    from src.agents.summary import SummaryAgent

    return SummaryAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_summarize_returns_structured_output(db_session, summary_agent, mock_llm):
    mock_llm.chat.return_value = (
        "讨论主题：项目排期\n"
        "关键结论：\n"
        "  - 周五前完成前端\n"
        "  - 下周一联调\n"
        "待办事项：\n"
        "  - @张三 提交接口文档\n"
        "决策：使用 FastAPI 作为后端框架"
    )

    result = await summary_agent.handle(
        intent="summarize_text",
        message="这是我们要总结的群聊文本内容...",
        user_id="assle",
        db=db_session,
    )

    assert "讨论主题" in result.reply
    assert "关键结论" in result.reply
    assert "待办事项" in result.reply
    assert "决策" in result.reply
    mock_llm.chat.assert_called_once()
