import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.schemas.response import AgentResponse
from src.models.preference import UserPreference, DEFAULT_PREFERENCES

QA_SYSTEM_PROMPT = """你是个人管家助手。根据用户偏好提供个性化回复。

用户偏好：
{preferences}

用友好、简洁的中文回复。"""


class QAAgent(BaseAgent):
    async def handle(
        self, intent: str, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        result = await db.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        pref = result.scalar_one_or_none()
        pref_json = json.loads(pref.preferences) if pref else DEFAULT_PREFERENCES

        preferences_summary = {
            "fitness": pref_json.get("fitness", {}),
            "meal": pref_json.get("meal", {}),
        }

        reply = await self._llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": QA_SYSTEM_PROMPT.format(
                        preferences=json.dumps(preferences_summary, ensure_ascii=False)
                    ),
                },
                {"role": "user", "content": message},
            ],
        )
        return AgentResponse(reply=reply)
