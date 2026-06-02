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
from src.agents.qa.graph import QAAgent
from src.knowledge.schemas import KnowledgeIngestRequest
from src.knowledge.service import KnowledgeService


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


@pytest.mark.asyncio
async def test_qa_agent_injects_knowledge_context(mock_llm, db_session):
    """验证 QAAgent 会把知识库片段注入 LLM prompt

    参数:
        mock_llm: 模拟 LLM 客户端
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 LLM system prompt 包含知识库资料
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="小管家资料",
            source="qa.md",
            content="小管家回答知识库问题时必须优先使用资料。",
            scope_type="public",
            scope_id=None,
            domain="qa",
            created_by="admin",
        ),
        db_session,
    )
    mock_llm.chat.return_value = "我会优先参考资料。"
    agent = QAAgent(mock_llm)

    result = await agent.handle("qa", "小管家回答知识库问题时应该怎么做？", "user_a", db_session)

    assert result.reply == "我会优先参考资料。"
    messages = mock_llm.chat.call_args.kwargs["messages"]
    system_prompt = messages[0]["content"]
    assert "以下是可参考的知识库资料" in system_prompt
    assert "小管家资料" in system_prompt
    assert "必须优先使用资料" in system_prompt


@pytest.mark.asyncio
async def test_qa_agent_uses_group_scope_when_extra_state_is_group(mock_llm, db_session):
    """验证 QAAgent 在群聊状态下检索群聊私有知识

    参数:
        mock_llm: 模拟 LLM 客户端
        db_session: 测试数据库会话

    返回:
        None；通过断言确认群聊资料进入 LLM prompt
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="群聊项目资料",
            source="group.md",
            content="群聊项目代号是青松。",
            scope_type="group",
            scope_id="chat_a",
            domain="qa",
            created_by="user_a",
        ),
        db_session,
    )
    mock_llm.chat.return_value = "项目代号是青松。"
    agent = QAAgent(mock_llm)

    await agent.handle(
        "qa",
        "项目代号是什么？",
        "user_a",
        db_session,
        extra_state={"chat_type": "group", "chat_id": "chat_a"},
    )

    messages = mock_llm.chat.call_args.kwargs["messages"]
    assert "群聊项目代号是青松" in messages[0]["content"]


@pytest.mark.asyncio
async def test_qa_agent_continues_when_knowledge_search_has_no_result(mock_llm, db_session):
    """验证知识库无命中时 QAAgent 仍然正常回复

    参数:
        mock_llm: 模拟 LLM 客户端
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 QA 回复不依赖知识命中
    """
    mock_llm.chat.return_value = "我暂时没有资料，但可以先给你一个保守回答。"
    agent = QAAgent(mock_llm)

    result = await agent.handle("qa", "一个没有资料的问题", "user_a", db_session)

    assert result.reply == "我暂时没有资料，但可以先给你一个保守回答。"
