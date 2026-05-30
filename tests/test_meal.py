"""
Meal Agent 测试
验证 MealAgent 的食谱生成功能

测试范围:
  - make_meal_plan: 查询偏好 → 检查训练 → 生成一日三餐食谱
"""
import json
import pytest
from src.models.preference import UserPreference, DEFAULT_PREFERENCES


@pytest.fixture
def meal_agent(mock_llm):
    """创建 MealAgent 实例，注入 mock LLM 客户端

    参数:
        mock_llm: conftest 提供的 AsyncMock LLM 客户端

    返回:
        MealAgent: 使用 mock LLM 的饮食 agent 实例
    """
    from src.agents.meal import MealAgent

    return MealAgent(llm_client=mock_llm)


@pytest.mark.asyncio
async def test_meal_plan_includes_nutrition(db_session, meal_agent, mock_llm):
    """验证食谱生成包含三餐和营养素估算

    预置用户偏好 → 模拟 LLM 返回含蛋白质/kcal 的食谱 → 验证格式完整。

    参数:
        db_session: 数据库会话 fixture
        meal_agent: MealAgent fixture
        mock_llm: mock LLM 客户端 fixture
    """
    pref = UserPreference(
        user_id="assle",
        preferences=json.dumps(DEFAULT_PREFERENCES, ensure_ascii=False),
    )
    db_session.add(pref)
    await db_session.flush()

    mock_llm.chat.return_value = (
        "早餐 (≈450 kcal)\n"
        "- 燕麦粥 (蛋白质12g, 碳水60g, 脂肪8g)\n"
        "- 煮鸡蛋×2 (蛋白质12g, 碳水1g, 脂肪10g)\n"
        "午餐 (≈700 kcal)\n"
        "- 鸡胸肉 (蛋白质40g, 碳水0g, 脂肪5g)\n"
        "- 糙米饭 (蛋白质5g, 碳水50g, 脂肪2g)\n"
        "晚餐 (≈550 kcal)\n"
        "- 三文鱼 (蛋白质35g, 碳水0g, 脂肪15g)\n"
        "- 炒蔬菜 (蛋白质3g, 碳水15g, 脂肪5g)"
    )

    result = await meal_agent.handle(
        intent="make_meal_plan",
        message="今天吃什么",
        user_id="assle",
        db=db_session,
    )

    assert "早餐" in result.reply
    assert "蛋白质" in result.reply
    assert "kcal" in result.reply
    mock_llm.chat.assert_called_once()
