"""引用审查服务"""
import logging
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchTask
from src.models.research_evidence import ResearchEvidence
from src.models.research_quality import (
    ResearchClaim,
    ResearchClaimEvidence,
    ResearchReviewFinding,
)
from src.research.review.prompts import CITATION_REVIEW_PROMPT
from src.research.review.schemas import CitationReview

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QualityDecision:
    """引用质量门判定"""
    outcome: Literal["pass", "repair", "fail"]
    unsupported_claim_keys: tuple[str, ...] = ()
    follow_up_queries: tuple[str, ...] = ()


class CitationReviewService:
    def __init__(self, *, llm, task_service):
        self._llm = llm
        self._tasks = task_service

    async def review(
        self, db: AsyncSession, task_id: str
    ) -> QualityDecision:
        task = await self._tasks.get_task(db, task_id)

        # 任务必须已处于 VALIDATING 状态（由协调器负责转换）
        # 1. load claims + evidence
        claims_result = await db.execute(
            select(ResearchClaim).where(
                ResearchClaim.workspace_id == task.workspace_id,
                ResearchClaim.task_id == task.id,
            )
        )
        claims = claims_result.scalars().all()

        if not claims:
            return QualityDecision(outcome="pass")

        # 3. build reviewer context
        claims_text_parts = []
        for c in claims:
            bindings = await db.execute(
                select(ResearchClaimEvidence, ResearchEvidence.excerpt)
                .join(ResearchEvidence, ResearchEvidence.id == ResearchClaimEvidence.evidence_id)
                .where(ResearchClaimEvidence.claim_id == c.id)
            )
            ev_parts = []
            for binding, excerpt in bindings.all():
                ev_parts.append(f"  Evidence {binding.evidence_id}: {excerpt[:300]}")
            claims_text_parts.append(
                f"Claim [{c.claim_key}] ({c.claim_type}): {c.text}\n"
                + "\n".join(ev_parts)
            )
        claims_text = "\n\n".join(claims_text_parts)

        # 4. invoke reviewer LLM
        prompt = CITATION_REVIEW_PROMPT.format(claims_text=claims_text)
        review: CitationReview = await self._llm.ainvoke_structured(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Review these claims against their evidence."},
            ],
            schema=CitationReview,
            temperature=0.1,
        )

        # 5. persist findings
        now = datetime.now(timezone.utc)
        for cr in review.claim_reviews:
            claim = next((c for c in claims if c.claim_key == cr.claim_key), None)
            if claim is None:
                continue
            claim.validation_status = cr.status
            for fd in cr.findings:
                db.add(ResearchReviewFinding(
                    workspace_id=task.workspace_id,
                    task_id=task.id,
                    report_id=claim.report_id,
                    claim_id=claim.id,
                    evidence_id=fd.evidence_id,
                    finding_type=fd.finding_type,
                    severity=fd.severity,
                    message=fd.message,
                    created_at=now,
                ))

        # 6. deterministic gate
        return _apply_quality_gate(claims, review)


def _apply_quality_gate(
    claims: list[ResearchClaim],
    review: CitationReview,
) -> QualityDecision:
    """确定性质量门：LLM pass 可被本地规则覆盖"""
    unsupported = []
    for c in claims:
        if c.material and c.validation_status == "unsupported":
            unsupported.append(c.claim_key)

    if unsupported:
        return QualityDecision(
            outcome="repair",
            unsupported_claim_keys=tuple(unsupported),
            follow_up_queries=tuple(review.missing_material_claims),
        )

    if review.decision == "pass":
        return QualityDecision(outcome="pass")
    elif review.decision == "repair":
        return QualityDecision(
            outcome="repair",
            follow_up_queries=tuple(review.missing_material_claims),
        )
    return QualityDecision(outcome="fail")
