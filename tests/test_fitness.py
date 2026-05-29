import json
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from src.models.training import TrainingRecord
from src.models.preference import UserPreference, DEFAULT_PREFERENCES


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def fitness_agent(mock_llm):
    from src.agents.fitness import FitnessAgent

    return FitnessAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_log_training_extracts_and_saves(db_session, fitness_agent, mock_llm):
    records_json = json.dumps([
        {
            "date": "2026-05-29",
            "muscle_group": "胸",
            "exercise": "卧推",
            "sets": 5,
            "reps": 8,
            "weight_kg": 80.0,
        },
        {
            "date": "2026-05-29",
            "muscle_group": "胸",
            "exercise": "飞鸟",
            "sets": 3,
            "reps": 12,
            "weight_kg": 15.0,
        },
    ])
    mock_llm.chat_json.return_value = records_json

    result = await fitness_agent.handle(
        intent="log_training",
        message="打卡 今天练胸 卧推80kg5组8次 飞鸟15kg3组12次",
        user_id="assle",
        db=db_session,
    )

    assert "已记录" in result.reply
    assert len(result.data["records"]) == 2

    stmt = select(TrainingRecord).where(TrainingRecord.user_id == "assle")
    db_result = await db_session.execute(stmt)
    records = db_result.scalars().all()
    assert len(records) == 2
    assert records[0].muscle_group == "胸"
    assert records[0].exercise == "卧推"
    assert records[0].weight_kg == 80.0


@pytest.mark.asyncio
async def test_today_plan_queries_history_and_generates(db_session, fitness_agent, mock_llm):
    from datetime import date, timedelta

    records = [
        TrainingRecord(
            user_id="assle",
            date=(date.today() - timedelta(days=i)).isoformat(),
            muscle_group=mg,
            exercise=ex,
            sets=3,
            reps=10,
            weight_kg=60.0,
        )
        for i, (mg, ex) in enumerate([
            ("胸", "卧推"), ("背", "引体向上"), ("腿", "深蹲"),
        ])
    ]
    for r in records:
        db_session.add(r)
    await db_session.flush()

    pref = UserPreference(
        user_id="assle",
        preferences=json.dumps(DEFAULT_PREFERENCES, ensure_ascii=False),
    )
    db_session.add(pref)
    await db_session.flush()

    mock_llm.chat.return_value = "今天建议练肩部，推荐动作：哑铃推举..."

    result = await fitness_agent.handle(
        intent="today_plan",
        message="今天练什么",
        user_id="assle",
        db=db_session,
    )

    assert "肩" in result.reply or "哑铃" in result.reply
    mock_llm.chat.assert_called_once()
