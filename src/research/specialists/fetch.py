"""
研究网页全文抓取 Specialist。
抓取经过安全校验的公开网页并生成证据。

Workflow:
1. 接收已规划的 URL。
2. 通过 SecuredFetcher 执行 SSRF 和响应大小控制。
3. 返回带 URL 和正文摘录的标准证据。
"""
from datetime import datetime, timezone

from src.research.evidence import EvidenceInput
from src.research.tools.schemas import ToolExecutionContext, ToolExecutionResult


class WebFetchResearcher:
    """抓取经过安全校验的公开网页并生成证据"""

    def __init__(self, fetcher):
        self._fetcher = fetcher

    async def execute(
        self,
        db,
        context: ToolExecutionContext,
        arguments: dict,
    ) -> ToolExecutionResult:
        """执行网页抓取

        参数:
            db: 数据库会话
            context: 工具执行上下文
            arguments: 包含 url 和可选 query/title 的参数

        返回:
            ToolExecutionResult
        """
        url = str(arguments.get("url", "")).strip()
        if not url:
            return ToolExecutionResult(success=False, error="缺少 url 参数")
        content = await self._fetcher.fetch(url)
        evidence = EvidenceInput(
            workspace_id=context.workspace_id,
            task_id=context.task_id,
            step_id=context.step_id,
            source_type="web",
            source_ref=url,
            title=str(arguments.get("title") or url),
            excerpt=content[:2000],
            query=str(arguments.get("query") or ""),
            retrieved_at=datetime.now(timezone.utc),
            confidence=None,
        )
        return ToolExecutionResult(
            success=True,
            data={"evidence": [evidence.model_dump(mode="json")]},
        )
