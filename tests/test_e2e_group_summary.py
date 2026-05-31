"""
群聊总结功能端到端集成测试
验证完整的 "发送群聊消息 → 静默收集 → 触发总结 → 结构化回复" 流程

测试范围:
  - 非触发群聊消息：静默保存到 DB，返回 collect_group 意图
  - 触发群聊消息：通过 summarize_group 生成结构化摘要
  - 不同群聊之间的消息隔离
  - LLM 收到的 prompt 包含群聊消息内容
"""
import json
from unittest.mock import patch

import pytest

import src.main


@pytest.mark.asyncio
async def test_e2e_group_silent_collect_and_summarize(http_client, db_session):
    """端到端：模拟群聊消息 → 静默收集 → 触发总结 → 结构化回复

    步骤 1：发送多条非触发群聊消息 → 验证静默保存（intent=collect_group）
    步骤 2：发送触发消息（"总结一下"） → 验证返回结构化摘要
    步骤 3：验证 LLM 收到的 prompt 包含群聊消息内容

    参数:
        http_client: httpx 异步客户端 fixture
        db_session: 数据库会话 fixture
    """
    chat_id = "e2e_test_group"

    # 步骤 1：发送多条非触发群聊消息（模拟群聊中的日常对话）
    normal_messages = [
        ("user_a", "明天下午三点开会，大家有空吗"),
        ("user_b", "我行的"),
        ("user_c", "三点可以，不过我要提前半小时走"),
        ("user_a", "好，那我们就三点到四点半，主要讨论新功能排期"),
        ("user_b", "收到，我准备一下设计文档"),
    ]

    for user_id, message in normal_messages:
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": user_id,
                "message": message,
                "chat_type": "group",
                "chat_id": chat_id,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["intent"] == "collect_group"
        assert body["data"]["saved"] is True
        assert body["response"] == ""

    # 步骤 2：发送触发消息（@机器人 总结一下）
    mock_summary = (
        "讨论主题：明天下午的会议安排和新功能排期讨论\n"
        "关键结论：\n"
        "  - 明天下午三点到四点半开会\n"
        "  - 主要讨论新功能排期\n"
        "  - user_b 负责准备设计文档\n"
        "待办事项：\n"
        "  - @user_b 准备设计文档\n"
        "  - @user_c 提前半小时离会，需提前同步进度\n"
        "决策：明天下午三点开会，讨论新功能排期\n"
        "未解决的问题：无"
    )

    with patch.object(
        src.main.llm_client,
        "chat",
        return_value=mock_summary,
    ) as mock_chat:
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "user_a",
                "message": "总结一下群消息",
                "chat_type": "group",
                "chat_id": chat_id,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "summarize_group"
    assert body["confidence"] == 1.0
    assert "讨论主题" in body["response"]
    assert "关键结论" in body["response"]
    assert "待办事项" in body["response"]
    assert "决策" in body["response"]

    # 步骤 3：验证 LLM 收到的 prompt 包含群聊消息内容
    mock_chat.assert_called_once()
    call_args = mock_chat.call_args
    user_message = call_args[1]["messages"][1]["content"]
    assert "明天下午三点开会" in user_message
    assert "user_a" in user_message
    assert "user_b" in user_message
    assert "准备一下设计文档" in user_message


@pytest.mark.asyncio
async def test_e2e_group_isolation(http_client, db_session):
    """端到端：验证不同群聊之间的消息隔离

    群 A 发消息 → 群 B 触发总结 → 不应包含群 A 的消息

    参数:
        http_client: httpx 异步客户端 fixture
        db_session: 数据库会话 fixture
    """
    # 群 A 发消息
    for user_id, message in [
        ("bob", "今天讨论新框架选型"),
        ("alice", "我倾向于继续用 FastAPI"),
    ]:
        await http_client.post(
            "/api/debug/message",
            json={
                "user_id": user_id,
                "message": message,
                "chat_type": "group",
                "chat_id": "group_a",
            },
        )

    # 群 B 发消息
    for user_id, message in [
        ("tom", "周末团建去哪里"),
        ("jerry", "去爬山吧"),
    ]:
        await http_client.post(
            "/api/debug/message",
            json={
                "user_id": user_id,
                "message": message,
                "chat_type": "group",
                "chat_id": "group_b",
            },
        )

    # 群 B 触发总结
    with patch.object(
        src.main.llm_client,
        "chat",
        return_value="讨论主题：周末团建\n关键结论：\n  - 去爬山\n待办事项：\n  - 无\n决策：去爬山\n未解决的问题：无",
    ) as mock_chat:
        await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "tom",
                "message": "总结一下群消息",
                "chat_type": "group",
                "chat_id": "group_b",
            },
        )

    # 群 B 的总结 prompt 应包含爬山但不包含框架选型（群 A 的消息）
    call_args = mock_chat.call_args
    user_message = call_args[1]["messages"][1]["content"]
    assert "爬山" in user_message
    assert "团建" in user_message
    assert "框架选型" not in user_message
    assert "FastAPI" not in user_message


@pytest.mark.asyncio
async def test_e2e_trigger_keyword_variants(http_client, db_session):
    """端到端：验证各种总结类关键词都能触发群聊总结

    参数:
        http_client: httpx 异步客户端 fixture
        db_session: 数据库会话 fixture
    """
    # 发送一条群聊消息作为历史
    await http_client.post(
        "/api/debug/message",
        json={
            "user_id": "user_1",
            "message": "今天需求评审通过了",
            "chat_type": "group",
            "chat_id": "trigger_test",
        },
    )

    keywords = ["总结一下最近的消息", "摘要", "概括一下", "汇总"]
    for trigger_msg in keywords:
        with patch.object(
            src.main.llm_client,
            "chat",
            return_value="讨论主题：需求评审\n关键结论：\n  - 通过了\n待办事项：\n  - 无\n决策：已通过\n未解决的问题：无",
        ):
            response = await http_client.post(
                "/api/debug/message",
                json={
                    "user_id": "user_1",
                    "message": trigger_msg,
                    "chat_type": "group",
                    "chat_id": "trigger_test",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["intent"] == "summarize_group", f"Failed for trigger: {trigger_msg}"
        assert len(body["response"]) > 0


@pytest.mark.asyncio
async def test_e2e_group_no_messages(http_client, db_session):
    """端到端：群聊无历史消息时触发总结 → 返回提示文本

    注意：由于触发消息本身也会被保存，因此 LLM 仍会被调用。
    真正的"空群聊"测试见 test_summary.py::test_summarize_group_empty_messages。

    参数:
        http_client: httpx 异步客户端 fixture
        db_session: 数据库会话 fixture
    """
    with patch.object(
        src.main.llm_client,
        "chat",
        return_value="暂无最近的群聊消息可供总结",
    ):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "user_1",
                "message": "总结一下群消息",
                "chat_type": "group",
                "chat_id": "empty_group_e2e",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "summarize_group"
    assert len(body["response"]) > 0
