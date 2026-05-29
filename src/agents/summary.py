from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.base import BaseAgent
from src.schemas.response import AgentResponse

SUMMARY_PROMPT = """你是群聊总结助手。用以下格式总结用户提供的聊天记录：

讨论主题：<一句话概括>
关键结论：
  - <结论1>
  - <结论2>
待办事项：
  - @<负责人> <事项>
决策：<已做出的决策，无则写"无">

只返回上述格式，不要有其他说明文字。"""


class SummaryAgent(BaseAgent):
    async def handle(
        self, intent: str, message: str, user_id: str, db: AsyncSession
    ) -> AgentResponse:
        reply = await self._llm.chat(
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": message},
            ],
        )
        return AgentResponse(reply=reply)
