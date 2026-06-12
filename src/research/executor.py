"""
Phase 1 研究执行器
在独立 Worker 中生成单次 LLM 初稿；不检索、不引用、不声称已经审核。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchReport
from src.research.service import ResearchTaskService


FOUNDATION_PROMPT = """你正在生成异步研究能力 Phase 1 的初步草稿。

要求：
- 回答用户问题并给出清晰结构；
- 明确区分事实、推断和建议；
- 不要伪造引用、链接或检索过程；
- 不要声称已经进行多来源研究或独立审核；
- 如果依赖最新资料，请明确写出"需要下一阶段联网检索核验"。

用户问题：
{question}
"""


class FoundationResearchExecutor:
    """单次 LLM 初稿执行器"""

    def __init__(self, task_service: ResearchTaskService, llm):
        """注入任务服务和 LLMClient"""
        self._tasks = task_service
        self._llm = llm

    async def execute(self, db: AsyncSession, task_id: str) -> ResearchReport:
        """幂等生成并持久化 unreviewed_foundation 报告"""
        existing = (
            await db.execute(
                select(ResearchReport).where(
                    ResearchReport.task_id == task_id,
                    ResearchReport.version == 1,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        task = await self._tasks.mark_running(db, task_id)
        body = await self._llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": FOUNDATION_PROMPT.format(question=task.question),
                },
                {"role": "user", "content": task.question},
            ],
            temperature=0.3,
        )
        clean_body = body.strip() or "未生成有效初稿。"
        summary = clean_body.replace("\n", " ")[:240]
        return await self._tasks.complete_with_report(
            db,
            task_id,
            summary=summary,
            body=clean_body,
            quality_status="unreviewed_foundation",
        )
