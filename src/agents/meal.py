import json
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.schemas.response import AgentResponse
from src.models.preference import UserPreference, DEFAULT_PREFERENCES
from src.models.training import TrainingRecord

MEAL_PROMPT = """你是营养师。根据用户信息和最近训练情况，生成一日三餐食谱。

要求：
- 每餐给出具体食物和营养素估算（蛋白质、碳水、脂肪、卡路里）
- 考虑用户热量目标、饮食类型、过敏原
- 有训练日提高蛋白质比例
- 用中文输出，格式如下：

早餐 (≈XXX kcal)
- 食物名 (蛋白质Xg, 碳水Xg, 脂肪Xg)
午餐 (≈XXX kcal)
- ...
晚餐 (≈XXX kcal)
- ..."""


class MealAgent(BaseAgent):
    async def handle(
        self, intent: str, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        result = await db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        pref = result.scalar_one_or_none()
        pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES

        cutoff = (date.today() - timedelta(days=1)).isoformat()
        result = await db.execute(
            select(TrainingRecord)
            .where(TrainingRecord.user_id == user_id)
            .where(TrainingRecord.date >= cutoff)
        )
        trained_today = result.scalars().all()

        context = (
            f"用户偏好：{json.dumps(pref_json['meal'], ensure_ascii=False)}\n"
            f"身体数据：{json.dumps(pref_json['fitness']['body'], ensure_ascii=False)}\n"
            f"训练目标：{pref_json['fitness']['goal']}\n"
            f"{'今天已训练，需要高蛋白' if trained_today else '今天未训练，维持饮食'}"
        )

        reply = await self._llm.chat(
            messages=[
                {"role": "system", "content": MEAL_PROMPT},
                {"role": "user", "content": context},
            ],
        )
        return AgentResponse(reply=reply)
