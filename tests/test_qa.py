"""
QA Agent 测试
验证 QAAgent 的个性化问答功能

测试范围:
  - 有偏好用户：偏好信息注入 system prompt
  - 新用户无偏好：使用默认偏好正常回复
"""
import json
import pytest
from src.models.preference import UserPreference, DEFAULT_PREFERENCES


@pytest.fixture
def qa_agent(mock_llm):
    """创建 QAAgent 实例，注入 mock LLM 客户端

    参数:
        mock_llm: conftest 提供的 AsyncMock LLM 客户端

    返回:
        QAAgent: 使用 mock LLM 的问答 agent 实例
    """
    from src.agents.qa import QAAgent

    return QAAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_qa_responds_with_user_context(db_session, qa_agent, mock_llm):
    """验证 QA 回复中包含用户偏好信息

    预置用户偏好（fitness + meal）→ 验证 system prompt 中包含偏好数据。

    参数:
        db_session: 数据库会话 fixture
        qa_agent: QAAgent fixture
        mock_llm: mock LLM 客户端 fixture
    """
    pref = UserPreference(
        user_id="assle",
        preferences=json.dumps(DEFAULT_PREFERENCES, ensure_ascii=False),
    )
    db_session.add(pref)
    await db_session.flush()

    mock_llm.chat.return_value = "你好！有什么可以帮你的？"

    result = await qa_agent.handle(
        intent="qa",
        message="你好",
        user_id="assle",
        db=db_session,
    )

    assert "你好" in result.reply
    mock_llm.chat.assert_called_once()

    call_messages = mock_llm.chat.call_args[1]["messages"]
    system_msg = call_messages[0]["content"]
    assert "fitness" in system_msg or "meal" in system_msg


@pytest.mark.asyncio
async def test_qa_without_preferences_works(db_session, qa_agent, mock_llm):
    """验证新用户（无偏好记录）的 QA 正常回复

    无 UserPreference 记录 → 使用 DEFAULT_PREFERENCES → 回复正常。

    参数:
        db_session: 数据库会话 fixture
        qa_agent: QAAgent fixture
        mock_llm: mock LLM 客户端 fixture
    """
    mock_llm.chat.return_value = "有什么可以帮你的？"

    result = await qa_agent.handle(
        intent="qa",
        message="你好",
        user_id="new_user",
        db=db_session,
    )

    assert len(result.reply) > 0
    mock_llm.chat.assert_called_once()
