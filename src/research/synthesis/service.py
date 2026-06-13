"""
研究报告综合服务
基于持久化证据生成结构化报告草稿，保存结论和证据绑定

Workflow:
1. 状态转换为 SYNTHESIZING
2. 加载工作空间内该任务的全部证据
3. 空证据时生成空报告
4. 构建证据摘要输入 LLM
5. LLM 生成结构化 ReportDraft
6. 校验引用合法性后持久化为 ResearchReport
7. 保存 ResearchClaim 和 ResearchClaimEvidence 绑定关系
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchReport, ResearchTask
from src.models.research_evidence import ResearchEvidence
from src.models.research_quality import ResearchClaim, ResearchClaimEvidence
from src.research.synthesis.prompts import SYNTHESIS_SYSTEM_PROMPT
from src.research.synthesis.schemas import ReportDraft, validate_report_draft

logger = logging.getLogger(__name__)


async def _next_version(db: AsyncSession, task_id: str) -> int:
    """查询研究任务下一版报告版本号

    参数:
        db: 异步数据库会话
        task_id: 研究任务 ID

    返回:
        int: 下一版版本号
    """
    existing = await db.execute(
        select(ResearchReport).where(
            ResearchReport.task_id == task_id,
        ).order_by(ResearchReport.version.desc()).limit(1)
    )
    latest = existing.scalar_one_or_none()
    return (latest.version + 1) if latest else 1


def _render_body(draft: ReportDraft) -> str:
    """渲染草稿为 markdown 正文

    参数:
        draft: ReportDraft 结构化报告草稿

    返回:
        str: markdown 正文
    """
    parts = [f"# {draft.title}\n\n{draft.summary}"]
    for sec in draft.sections:
        parts.append(f"\n## {sec.heading}\n\n{sec.body}")
    if draft.limitations:
        parts.append("\n## 局限性\n")
        for lim in draft.limitations:
            parts.append(f"- {lim}")
    return "\n".join(parts)


class ReportSynthesisService:
    """基于持久化证据生成并保存报告草稿"""

    def __init__(self, *, llm, task_service):
        """初始化综合服务

        参数:
            llm: LLM 客户端，支持 .ainvoke_structured()
            task_service: ResearchTaskService 实例
        """
        self._llm = llm
        self._tasks = task_service

    async def synthesize(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> ResearchReport:
        """生成结构化报告草稿

        参数:
            db: 异步数据库会话
            task_id: 研究任务 ID

        返回:
            ResearchReport: 已保存的草稿版本
        """
        task = await self._tasks.get_task(db, task_id)

        # 任务必须已处于 SYNTHESIZING 状态（由协调器负责转换）
        # 1. 加载证据
        evidence_result = await db.execute(
            select(ResearchEvidence).where(
                ResearchEvidence.workspace_id == task.workspace_id,
                ResearchEvidence.task_id == task.id,
            ).order_by(ResearchEvidence.created_at)
        )
        evidence_rows = evidence_result.scalars().all()
        allowed_ids = {e.id for e in evidence_rows}

        if not evidence_rows:
            # 无证据时生成空报告
            version = await _next_version(db, task_id)
            report = ResearchReport(
                task_id=task_id,
                version=version,
                workspace_id=task.workspace_id,
                summary="未检索到相关证据",
                body="本轮研究未找到可验证的证据。",
                quality_status="unreviewed_foundation",
                report_status="draft",
            )
            db.add(report)
            await db.flush()
            return report

        # 3. 构建证据摘要
        evidence_parts = []
        for e in evidence_rows:
            evidence_parts.append(
                f"[Evidence ID: {e.id}] Title: {e.title}\n"
                f"Source: {e.source_ref}\n"
                f"Excerpt: {e.excerpt[:500]}\n"
                f"Type: {e.source_type}, Query: {e.query}"
            )
        evidence_summary = "\n\n---\n\n".join(evidence_parts)

        # 4. LLM 结构化输出
        prompt = SYNTHESIS_SYSTEM_PROMPT.format(
            question=task.question,
            evidence_summary=evidence_summary,
        )
        draft: ReportDraft = await self._llm.ainvoke_structured(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": task.question},
            ],
            schema=ReportDraft,
            temperature=0.2,
        )

        # 5. 校验
        validate_report_draft(draft, allowed_evidence_ids=allowed_ids)

        # 6. 持久化
        version = await _next_version(db, task_id)
        report = ResearchReport(
            task_id=task_id,
            version=version,
            workspace_id=task.workspace_id,
            summary=draft.summary,
            body=_render_body(draft),
            quality_status="citation_reviewed",
            report_status="draft",
        )
        db.add(report)
        await db.flush()

        # 7. 保存结论和证据绑定
        for claim_draft in draft.claims:
            claim = ResearchClaim(
                workspace_id=task.workspace_id,
                task_id=task_id,
                report_id=report.id,
                claim_key=claim_draft.key,
                text=claim_draft.text,
                claim_type=claim_draft.claim_type,
                material=claim_draft.material,
            )
            db.add(claim)
            await db.flush()

            for ev_id in claim_draft.evidence_ids:
                db.add(ResearchClaimEvidence(
                    workspace_id=task.workspace_id,
                    claim_id=claim.id,
                    evidence_id=ev_id,
                    support_level="supports",
                    rationale=claim_draft.text[:100],
                ))

        await db.flush()
        logger.info(
            "Synthesis: report version=%d task=%s claims=%d",
            version, task_id, len(draft.claims),
        )
        return report
