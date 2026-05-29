import json
from unittest.mock import AsyncMock
import pytest
from src.models.preference import UserPreference, DEFAULT_PREFERENCES


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def qa_agent(mock_llm):
    from src.agents.qa import QAAgent

    return QAAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_qa_responds_with_user_context(db_session, qa_agent, mock_llm):
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
    mock_llm.chat.return_value = "有什么可以帮你的？"

    result = await qa_agent.handle(
        intent="qa",
        message="你好",
        user_id="new_user",
        db=db_session,
    )

    assert len(result.reply) > 0
    mock_llm.chat.assert_called_once()
