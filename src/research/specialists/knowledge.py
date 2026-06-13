"""知识库研究 Specialist"""
import logging
from datetime import datetime, timezone

from src.research.tools.schemas import ToolExecutionContext, ToolExecutionResult
from src.research.specialists.schemas import RetrievalResult
from src.research.evidence import EvidenceInput

logger = logging.getLogger(__name__)


class KnowledgeResearcher:
    """从授权知识库检索并产生归一化证据"""

    def __init__(self, gateway):
        self._gateway = gateway

    async def execute(
        self,
        db,
        context: ToolExecutionContext,
        arguments: dict,
    ) -> ToolExecutionResult:
        """执行知识检索

        参数:
            db: 数据库会话
            context: 工具执行上下文
            arguments: 包含 query 字段的参数

        返回:
            ToolExecutionResult
        """
        from src.research.sources import ResearchAccessScope

        query = arguments.get("query", "")
        if not query:
            return ToolExecutionResult(success=False, error="缺少查询参数")

        scope = ResearchAccessScope(
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            include_public=True,
        )

        try:
            results = await self._gateway.search_knowledge(
                scope, query, db=db, limit=5,
            )
        except Exception as e:
            logger.warning("Knowledge researcher: search failed: %s", e)
            return ToolExecutionResult(
                success=False, error=f"知识检索失败: {e}",
            )

        if not results:
            return ToolExecutionResult(
                success=True,
                data={
                    "summary": "未找到相关知识",
                    "evidence_count": 0,
                },
            )

        now = datetime.now(timezone.utc)
        evidence = []
        for r in results:
            evidence.append(EvidenceInput(
                workspace_id=context.workspace_id,
                task_id=context.task_id,
                step_id=context.step_id,
                source_type="knowledge",
                source_ref=f"knowledge://{r.source or 'unknown'}",
                title=r.title or "Untitled",
                excerpt=r.content[:500],
                query=query,
                retrieved_at=now,
                confidence=None,
            ))

        return ToolExecutionResult(
            success=True,
            data={
                "summary": f"找到 {len(evidence)} 条相关知识",
                "evidence": [e.model_dump(mode="json") for e in evidence],
                "evidence_count": len(evidence),
            },
        )
