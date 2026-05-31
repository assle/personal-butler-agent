"""
Summary Agent 测试
验证 SummaryAgent 的私聊文本总结和群聊消息总结功能

测试范围:
  - summarize_text: 生成包含讨论主题、关键结论、待办事项、决策的结构化摘要
  - summarize_group: 从数据库获取群聊消息后生成结构化摘要
  - 条件路由: chat_type="group" 走 summarize_group 节点
"""
import pytest

from src.models.group_message import GroupMessage


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
async def test_summarize_text_returns_structured_output(db_session, summary_agent, mock_llm):
    """验证私聊文本总结包含所有必需的四个部分

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


@pytest.mark.asyncio
async def test_summarize_group_fetches_and_summarizes(db_session, summary_agent, mock_llm):
    """验证群聊总结：从 DB 获取消息并调用 LLM 总结

    先在 group_messages 表中写入模拟群聊消息，然后以 chat_type="group" 调用 handle，
    验证 LLM 收到的 prompt 包含群聊消息内容。

    参数:
        db_session: 数据库会话 fixture
        summary_agent: SummaryAgent fixture
        mock_llm: mock LLM 客户端 fixture
    """
    # 写入模拟群聊消息
    chat_id = "test_group_chat_1"
    messages_data = [
        ("user_a", "明天什么时候开会", 1000),
        ("user_b", "下午三点可以吗", 1001),
        ("user_c", "我没问题", 1002),
        ("user_a", "好，那就三点", 1003),
        ("user_b", "收到，我准备一下材料", 1004),
    ]
    for user_id, content, create_time in messages_data:
        await GroupMessage.save(db_session, chat_id, user_id, content, create_time)

    mock_llm.chat.return_value = (
        "讨论主题：会议时间确认\n"
        "关键结论：\n"
        "  - 明天下午三点开会\n"
        "  - user_b 负责准备材料\n"
        "待办事项：\n"
        "  - @user_b 准备会议材料\n"
        "决策：明天下午三点全体会议\n"
        "未解决的问题：无"
    )

    result = await summary_agent.handle(
        intent="summarize_group",
        message="@机器人 总结一下群消息",
        user_id="user_a",
        db=db_session,
        extra_state={"chat_id": chat_id, "chat_type": "group"},
    )

    assert "讨论主题" in result.reply
    assert "关键结论" in result.reply
    assert "待办事项" in result.reply
    assert "决策" in result.reply

    # 验证 LLM 收到的 prompt 包含群聊消息内容
    call_args = mock_llm.chat.call_args
    user_message = call_args[1]["messages"][1]["content"]
    assert "user_a" in user_message
    assert "user_b" in user_message
    assert "明天什么时候开会" in user_message


@pytest.mark.asyncio
async def test_summarize_group_empty_messages(db_session, summary_agent, mock_llm):
    """验证群聊总结：无消息时返回提示而非调用 LLM

    输入: 空数据库，chat_type="group"
    输出: 返回提示文本，LLM 未被调用
    """
    result = await summary_agent.handle(
        intent="summarize_group",
        message="@机器人 总结一下群消息",
        user_id="user_a",
        db=db_session,
        extra_state={"chat_id": "empty_group", "chat_type": "group"},
    )

    assert "暂无" in result.reply
    mock_llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_group_routes_correctly(db_session, summary_agent, mock_llm):
    """验证条件路由：chat_type="group" 走 summarize_group 节点

    有 chat_type="group" + 数据库中有消息 → 应通过 summarize_group 路径处理

    参数:
        db_session: 数据库会话 fixture
        summary_agent: SummaryAgent fixture
        mock_llm: mock LLM 客户端 fixture
    """
    # 写入一条群聊消息
    await GroupMessage.save(
        db_session, "route_test_group", "user_x",
        "今天要完成什么任务", 2000,
    )

    mock_llm.chat.return_value = (
        "讨论主题：今日任务\n"
        "关键结论：\n  - 需要完成任务\n"
        "待办事项：\n  - @user_x 完成任务\n"
        "决策：无\n"
        "未解决的问题：无"
    )

    result = await summary_agent.handle(
        intent="summarize_group",
        message="总结一下",
        user_id="user_x",
        db=db_session,
        extra_state={"chat_id": "route_test_group", "chat_type": "group"},
    )

    assert "讨论主题" in result.reply
    mock_llm.chat.assert_called_once()
    # 验证 LLM 收到的消息包含群聊消息而非原始 message
    call_args = mock_llm.chat.call_args
    user_message = call_args[1]["messages"][1]["content"]
    assert "今天要完成什么任务" in user_message


def test_route_by_chat_type():
    """验证路由函数：根据 chat_type 返回正确节点名"""
    from src.agents.summary.graph import _route_by_chat_type

    assert _route_by_chat_type({"chat_type": "group"}) == "summarize_group"
    assert _route_by_chat_type({"chat_type": "single"}) == "generate"
    assert _route_by_chat_type({}) == "generate"
