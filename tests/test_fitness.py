"""
Fitness Agent 测试
验证 FitnessAgent 的 training log 记录和 training plan 生成功能

测试范围:
  - log_training: LLM 提取 → 入库 → 格式化回复
  - today_plan: 查询历史 → 查询偏好 → 生成计划
"""
import json
import pytest
from sqlalchemy import select
from src.models.training import TrainingRecord
from src.models.preference import UserPreference, DEFAULT_PREFERENCES


@pytest.fixture
def fitness_agent(mock_llm):
    """创建 FitnessAgent 实例，注入 mock LLM 客户端

    参数:
        mock_llm: conftest 提供的 AsyncMock LLM 客户端

    返回:
        FitnessAgent: 使用 mock LLM 的健身 agent 实例
    """
    from src.agents.fitness import FitnessAgent

    return FitnessAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_log_training_extracts_and_saves(db_session, fitness_agent, mock_llm):
    """验证 log_training 意图：LLM 提取 → 入库 → 回复

    模拟 LLM 返回 2 条训练记录 → 验证数据库写入 2 条 → 验证回复和数据字段。

    参数:
        db_session: 数据库会话 fixture
        fitness_agent: FitnessAgent fixture
        mock_llm: mock LLM 客户端 fixture
    """
    records_json = json.dumps([
        {
            "training_type": "strength",
            "date": "2026-05-29",
            "muscle_group": "胸",
            "exercise": "卧推",
            "sets": 5,
            "reps": 8,
            "weight_kg": 80.0,
        },
        {
            "training_type": "strength",
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
async def test_log_training_cardio_extracts_and_saves(db_session, fitness_agent, mock_llm):
    """验证 log_training 意图对有氧训练的支持：LLM 提取 → 入库 → 回复

    模拟 LLM 返回 1 条有氧训练记录 → 验证数据库写入 → 验证回复包含有氧信息。

    参数:
        db_session: 数据库会话 fixture
        fitness_agent: FitnessAgent fixture
        mock_llm: mock LLM 客户端 fixture
    """
    records_json = json.dumps([
        {
            "training_type": "cardio",
            "date": "2026-06-01",
            "exercise": "爬坡",
            "duration_minutes": 30,
            "speed": 4.6,
            "incline": 13,
            "calories": 150,
        },
    ])
    mock_llm.chat_json.return_value = records_json

    result = await fitness_agent.handle(
        intent="log_training",
        message="打卡 昨天练了爬坡，坡度13，速度4.6，时间30分钟 消耗150卡",
        user_id="assle",
        db=db_session,
    )

    assert "已记录" in result.reply
    assert "爬坡" in result.reply
    assert len(result.data["records"]) == 1
    assert result.data["records"][0]["training_type"] == "cardio"
    assert result.data["records"][0]["calories"] == 150

    stmt = select(TrainingRecord).where(TrainingRecord.user_id == "assle")
    db_result = await db_session.execute(stmt)
    records = db_result.scalars().all()
    assert len(records) == 1
    assert records[0].training_type == "cardio"
    assert records[0].exercise == "爬坡"
    assert records[0].duration_minutes == 30
    assert records[0].incline == 13
    assert records[0].calories == 150


@pytest.mark.asyncio
async def test_today_plan_queries_history_and_generates(db_session, fitness_agent, mock_llm):
    """验证 today_plan 意图：查询历史 → 偏好 → 生成计划

    预置 3 天训练记录和用户偏好 → 模拟 LLM 返回训练建议 → 验证包含推荐部位。

    参数:
        db_session: 数据库会话 fixture
        fitness_agent: FitnessAgent fixture
        mock_llm: mock LLM 客户端 fixture
    """
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
