"""
端到端烟雾测试
验证完整的请求 → 意图路由 → agent → 响应流程

测试范围:
  - log_training 卡片记录后请求 today_plan（多步交互）
  - summarize_text 群聊总结完整流程
"""
import json
from unittest.mock import patch

import pytest

import src.main


@pytest.mark.asyncio
async def test_full_flow_log_training_to_plan(http_client, db_session):
    """端到端：先打卡记录训练，再请求训练计划

    步骤 1：发送打卡消息 → 验证意图=log_training，数据落地
    步骤 2：发送训练计划请求 → 验证意图=today_plan，回复非空

    参数:
        http_client: httpx 异步客户端 fixture
        db_session: 数据库会话 fixture
    """
    # 步骤 1：打卡记录训练
    with patch.object(
        src.main.llm_client,
        "chat_json",
        return_value=json.dumps([
            {
                "date": "2026-05-29",
                "muscle_group": "腿",
                "exercise": "深蹲",
                "sets": 5,
                "reps": 5,
                "weight_kg": 100.0,
            }
        ]),
    ):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "打卡 深蹲100kg5组5次",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "log_training"
    assert body["data"]["records"][0]["exercise"] == "深蹲"

    # 步骤 2：请求训练计划
    with patch.object(
        src.main.llm_client,
        "chat",
        return_value="根据你最近的训练，建议今天练胸：平板卧推 4×8...",
    ):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "今天练什么",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "today_plan"
    assert len(body["response"]) > 0


@pytest.mark.asyncio
async def test_full_flow_summarize(http_client, db_session):
    """端到端：通过调试端点发送群聊总结请求

    模拟 LLM 返回结构化摘要 → 验证意图=summarize_text。

    参数:
        http_client: httpx 异步客户端 fixture
        db_session: 数据库会话 fixture
    """
    with patch.object(
        src.main.llm_client,
        "chat",
        return_value=(
            "讨论主题：版本发布\n"
            "关键结论：\n"
            "  - 周五发版\n"
            "待办事项：\n"
            "  - 无\n"
            "决策：正常发布"
        ),
    ):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "帮我总结：张三说周五发版，李四同意了。",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "summarize_text"
