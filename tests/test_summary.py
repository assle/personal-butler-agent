"""
Summary Agent 测试
验证 SummaryAgent 的群聊摘要结构化输出功能

测试范围:
  - summarize_text: 生成包含讨论主题、关键结论、待办事项、决策的结构化摘要
"""
import pytest


@pytest.fixture
def summary_agent(mock_llm):
    """创建 SummaryAgent 实例，注入 mock LLM 客户端

    参数:
        mock_llm: conftest 提供的 AsyncMock LLM 客户端

    返回:
        SummaryAgent: 使用 mock LLM 的摘要 agent 实例
    """
    from src.agents.summary import SummaryAgent

    return SummaryAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_summarize_returns_structured_output(db_session, summary_agent, mock_llm):
    """验证群聊摘要包含所有必需的四个部分

    模拟 LLM 返回结构化摘要 → 验证"讨论主题""关键结论""待办事项""决策"四个字段存在。

    参数:
        db_session: 数据库会话 fixture
        summary_agent: SummaryAgent fixture
        mock_llm: mock LLM 客户端 fixture
    """
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
