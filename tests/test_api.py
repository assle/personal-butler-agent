import json
from unittest.mock import patch
import pytest
import src.main


@pytest.mark.asyncio
async def test_debug_endpoint_log_training(http_client, db_session):
    with patch.object(
        src.main.llm_client,
        "chat_json",
        return_value=json.dumps([
            {
                "date": "2026-05-29",
                "muscle_group": "胸",
                "exercise": "卧推",
                "sets": 5,
                "reps": 8,
                "weight_kg": 80.0,
            }
        ]),
    ):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "打卡 今天练胸 卧推80kg5组8次",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "log_training"
    assert body["confidence"] == 1.0
    assert "卧推" in body["response"]


@pytest.mark.asyncio
async def test_debug_endpoint_qa(http_client, db_session):
    with patch.object(
        src.main.llm_client,
        "chat_json",
        return_value='{"intent": "qa", "confidence": 1.0}',
    ):
        with patch.object(
            src.main.llm_client,
            "chat",
            return_value="你好！有什么可以帮你的？",
        ):
            response = await http_client.post(
                "/api/debug/message",
                json={
                    "user_id": "assle",
                    "message": "你好",
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "qa"
    assert body["confidence"] == 1.0
    assert len(body["response"]) > 0
