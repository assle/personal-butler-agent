"""End-to-end smoke tests for the Personal Butler Agent MVP.

These tests exercise the full request -> intent routing -> agent -> response flow
by mocking the LLM client on the real shared instance in src.main.
"""

import json
from unittest.mock import patch

import pytest

import src.main


@pytest.mark.asyncio
async def test_full_flow_log_training_to_plan(http_client, db_session):
    """Full flow: log training, then ask for today's plan."""
    # Step 1: log training
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

    # Step 2: ask for plan
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
    """Full flow: summarize chat text through the debug endpoint."""
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
