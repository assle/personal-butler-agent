"""联网研究 Specialist"""
import logging
from datetime import datetime, timezone

from src.research.tools.schemas import ToolExecutionContext, ToolExecutionResult
from src.research.evidence import EvidenceInput

logger = logging.getLogger(__name__)


class WebResearcher:
    """从公开网页检索并产生归一化证据"""

    def __init__(self, web_search_service):
        self._web = web_search_service

    async def execute(
        self,
        db,
        context: ToolExecutionContext,
        arguments: dict,
    ) -> ToolExecutionResult:
        """执行联网检索

        参数:
            db: 数据库会话
            context: 工具执行上下文
            arguments: 包含 query 字段的参数
        """
        query = arguments.get("query", "")
        if not query:
            return ToolExecutionResult(success=False, error="缺少查询参数")

        try:
            results = await self._web.search(query)
        except Exception as e:
            logger.warning("Web researcher: search failed: %s", e)
            return ToolExecutionResult(
                success=False, error=f"联网检索失败: {e}",
            )

        if not results:
            return ToolExecutionResult(
                success=True,
                data={"summary": "未找到相关网页", "evidence_count": 0},
            )

        now = datetime.now(timezone.utc)
        evidence = []
        for r in results:
            evidence.append(EvidenceInput(
                workspace_id=context.workspace_id,
                task_id=context.task_id,
                step_id=context.step_id,
                source_type="web",
                source_ref=r.url if hasattr(r, 'url') else str(r),
                title=getattr(r, 'title', 'Untitled') or 'Untitled',
                excerpt=getattr(r, 'snippet', '')[:500],
                query=query,
                retrieved_at=now,
                confidence=getattr(r, 'confidence', None),
            ))

        return ToolExecutionResult(
            success=True,
            data={
                "summary": f"找到 {len(evidence)} 条网页结果",
                "evidence": [e.model_dump(mode="json") for e in evidence],
                "evidence_count": len(evidence),
            },
        )
