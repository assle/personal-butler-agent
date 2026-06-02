"""
知识库服务测试
验证文档入库、scope 权限过滤、domain 过滤和关键词检索

Workflow:
  KnowledgeService.ingest() 写入文档和 chunk → search() 按用户/群聊权限返回结果
"""
import pytest

from src.knowledge.schemas import KnowledgeIngestRequest
from src.knowledge.service import KnowledgeService


@pytest.mark.asyncio
async def test_search_returns_public_knowledge(db_session):
    """验证任何用户都能检索 public 知识

    参数:
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 public chunk 可见
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="公共健身知识",
            source="public.md",
            content="深蹲时要保持核心稳定。",
            scope_type="public",
            scope_id=None,
            domain="qa",
            created_by="admin",
        ),
        db_session,
    )

    results = await service.search(
        query="深蹲",
        user_id="user_a",
        chat_type="single",
        chat_id=None,
        domains=["global", "qa"],
        db=db_session,
    )

    assert len(results) == 1
    assert results[0].title == "公共健身知识"
    assert "核心稳定" in results[0].content


@pytest.mark.asyncio
async def test_user_private_scope_is_isolated(db_session):
    """验证用户只能检索自己的私有知识

    参数:
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 user scope 不越权
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="A 的资料",
            source="a.md",
            content="用户 A 喜欢低碳饮食。",
            scope_type="user",
            scope_id="user_a",
            domain="qa",
            created_by="user_a",
        ),
        db_session,
    )
    await service.ingest(
        KnowledgeIngestRequest(
            title="B 的资料",
            source="b.md",
            content="用户 B 喜欢高碳饮食。",
            scope_type="user",
            scope_id="user_b",
            domain="qa",
            created_by="user_b",
        ),
        db_session,
    )

    results = await service.search(
        query="饮食",
        user_id="user_a",
        chat_type="single",
        chat_id=None,
        domains=["qa"],
        db=db_session,
    )

    titles = {item.title for item in results}
    assert titles == {"A 的资料"}


@pytest.mark.asyncio
async def test_group_private_scope_is_isolated(db_session):
    """验证群聊只能检索本群私有知识

    参数:
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 group scope 不越权
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="群 A 项目资料",
            source="group-a.md",
            content="项目代号是青松。",
            scope_type="group",
            scope_id="chat_a",
            domain="qa",
            created_by="user_a",
        ),
        db_session,
    )
    await service.ingest(
        KnowledgeIngestRequest(
            title="群 B 项目资料",
            source="group-b.md",
            content="项目代号是海棠。",
            scope_type="group",
            scope_id="chat_b",
            domain="qa",
            created_by="user_b",
        ),
        db_session,
    )

    results = await service.search(
        query="项目代号",
        user_id="user_a",
        chat_type="group",
        chat_id="chat_a",
        domains=["qa"],
        db=db_session,
    )

    assert [item.title for item in results] == ["群 A 项目资料"]
    assert "青松" in results[0].content


@pytest.mark.asyncio
async def test_group_search_does_not_read_user_private_knowledge(db_session):
    """验证群聊检索不会读取发言人的个人私有知识

    参数:
        db_session: 测试数据库会话

    返回:
        None；通过断言确认群聊不混用 user scope
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="用户 A 私有资料",
            source="user-a.md",
            content="用户 A 的私人目标是增肌。",
            scope_type="user",
            scope_id="user_a",
            domain="qa",
            created_by="user_a",
        ),
        db_session,
    )

    results = await service.search(
        query="私人目标",
        user_id="user_a",
        chat_type="group",
        chat_id="chat_a",
        domains=["qa"],
        db=db_session,
    )

    assert results == []


@pytest.mark.asyncio
async def test_domain_filter_blocks_unrelated_chunks(db_session):
    """验证 domain 过滤会排除不相关领域知识

    参数:
        db_session: 测试数据库会话

    返回:
        None；通过断言确认 QA 检索不会拿到 fitness-only chunk
    """
    service = KnowledgeService()
    await service.ingest(
        KnowledgeIngestRequest(
            title="健身专用资料",
            source="fitness.md",
            content="训练计划需要渐进超负荷。",
            scope_type="public",
            scope_id=None,
            domain="fitness",
            created_by="admin",
        ),
        db_session,
    )

    results = await service.search(
        query="训练计划",
        user_id="user_a",
        chat_type="single",
        chat_id=None,
        domains=["qa"],
        db=db_session,
    )

    assert results == []


def test_ingest_request_rejects_invalid_private_scope():
    """验证私有知识缺少 scope_id 时会被拒绝

    参数:
        无

    返回:
        None；通过断言确认非法导入请求抛出 ValueError
    """
    service = KnowledgeService()
    request = KnowledgeIngestRequest(
        title="非法资料",
        source="invalid.md",
        content="这份资料缺少用户或群聊 ID。",
        scope_type="user",
        scope_id=None,
        domain="qa",
        created_by="user_a",
    )

    with pytest.raises(ValueError, match="Private knowledge must have scope_id"):
        service._validate_request(request)
