import json
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.schemas.response import AgentResponse
from src.models.training import TrainingRecord
from src.models.preference import UserPreference, DEFAULT_PREFERENCES

EXTRACTION_PROMPT = """从用户消息中提取训练记录。返回 JSON 数组，每条记录包含：
- date: 训练日期 YYYY-MM-DD（未指定则用今天）
- muscle_group: 训练部位（胸/背/腿/肩/臂/核心）
- exercise: 动作名称
- sets: 组数（整数）
- reps: 次数（整数）
- weight_kg: 重量kg（自重训练可为null）

如果无法提取任何记录，返回空数组 []。
只返回 JSON，不要有其他文字。"""

PLAN_PROMPT = """你是健身教练。根据用户最近的训练记录和偏好，生成今日训练建议。
考虑：部位轮换（避免连续练同一部位）、用户目标和水平。
用自然语言给出建议部位、推荐动作、组数次数。"""


class FitnessAgent(BaseAgent):
    async def handle(
        self, intent: str, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        if intent == "log_training":
            return await self._log_training(message, user_id, db)
        elif intent == "today_plan":
            return await self._today_plan(message, user_id, db)
        return AgentResponse(reply="Unknown fitness intent")

    async def _log_training(
        self, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        raw = await self._llm.chat_json(
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": message},
            ],
        )
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            return AgentResponse(reply="无法解析训练记录，请确认格式后重试。")

        if not items:
            return AgentResponse(reply="未识别到训练记录。示例格式：打卡 今天练胸 卧推80kg5组8次")

        saved = []
        for item in items:
            record = TrainingRecord(
                user_id=user_id,
                date=item.get("date", date.today().isoformat()),
                muscle_group=item["muscle_group"],
                exercise=item["exercise"],
                sets=item["sets"],
                reps=item["reps"],
                weight_kg=item.get("weight_kg"),
            )
            db.add(record)
            saved.append(
                {
                    "muscle_group": record.muscle_group,
                    "exercise": record.exercise,
                    "sets": record.sets,
                    "reps": record.reps,
                    "weight_kg": record.weight_kg,
                }
            )

        await db.flush()
        return AgentResponse(
            reply=f"已记录 {len(saved)} 条训练：{'、'.join(r['exercise'] for r in saved)}",
            data={"records": saved},
        )

    async def _today_plan(
        self, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        result = await db.execute(
            select(TrainingRecord)
            .where(TrainingRecord.user_id == user_id)
            .where(TrainingRecord.date >= cutoff)
            .order_by(TrainingRecord.date.desc())
        )
        recent = result.scalars().all()

        result = await db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        pref = result.scalar_one_or_none()
        pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES

        history_text = "\n".join(
            f"- {r.date}: {r.muscle_group} {r.exercise} {r.sets}×{r.reps}"
            + (f" {r.weight_kg}kg" if r.weight_kg else "")
            for r in recent
        ) if recent else "暂无训练记录"

        reply = await self._llm.chat(
            messages=[
                {"role": "system", "content": PLAN_PROMPT},
                {
                    "role": "user",
                    "content": f"用户偏好：{json.dumps(pref_json['fitness'], ensure_ascii=False)}\n最近训练：\n{history_text}\n请给出今日训练建议。",
                },
            ],
        )
        return AgentResponse(reply=reply)
