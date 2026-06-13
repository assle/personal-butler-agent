"""
研究证据服务
负责证据的规范化存储、SHA-256 去重和查询

Workflow:
1. EvidenceInput 由执行步骤提交，包含完整元数据和内容摘要
2. store() 使用 SHA-256(source_ref + excerpt) 去重，同工作空间相同 hash 复用
3. list_by_task() 按创建时间排序返回任务全部证据，供报告合成阶段使用
"""
import hashlib
import logging
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research_evidence import ResearchEvidence

logger = logging.getLogger(__name__)


class EvidenceInput(BaseModel):
    """研究证据写入输入

    参数:
        workspace_id: 工作空间 ID
        task_id: 研究任务 ID
        step_id: 产生此证据的步骤 ID
        source_type: 证据来源类型（knowledge | web）
        source_ref: 原始来源 URL 或知识库文档 ID
        title: 文档标题
        publisher: 发布者/来源名称
        published_at: 原始发布时间
        retrieved_at: 检索时间
        excerpt: 证据内容摘要
        query: 检索时使用的查询语句
        confidence: 证据可信度 0-1
        metadata: 额外元数据字典
    """

    workspace_id: str
    task_id: str
    step_id: str
    source_type: Literal["knowledge", "web"]
    source_ref: str = Field(min_length=1)
    title: str = Field(min_length=1)
    publisher: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    excerpt: str = Field(min_length=1)
    query: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: dict = Field(default_factory=dict)


class ResearchEvidenceService:
    """去重并持久化研究证据"""

    @staticmethod
    def _hash(source_ref: str, excerpt: str) -> str:
        """计算 SHA-256 去重哈希

        参数:
            source_ref: 来源引用
            excerpt: 内容摘要

        返回:
            str: SHA-256 十六进制摘要
        """
        return hashlib.sha256(
            f"{source_ref}\n{excerpt}".encode("utf-8")
        ).hexdigest()

    async def store(
        self, db: AsyncSession, input_: EvidenceInput
    ) -> ResearchEvidence:
        """存储证据；同工作空间相同内容只保存一次

        参数:
            db: 异步数据库会话
            input_: 证据输入

        返回:
            ResearchEvidence: 新建或已存在的证据
        """
        content_hash = self._hash(input_.source_ref, input_.excerpt)

        # 去重：同工作空间相同 hash 即复用
        existing = await db.execute(
            select(ResearchEvidence).where(
                ResearchEvidence.workspace_id == input_.workspace_id,
                ResearchEvidence.content_hash == content_hash,
            )
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            logger.debug("Evidence: dedup hash=%s", content_hash[:16])
            return row

        evidence = ResearchEvidence(
            workspace_id=input_.workspace_id,
            task_id=input_.task_id,
            step_id=input_.step_id,
            source_type=input_.source_type,
            source_ref=input_.source_ref,
            title=input_.title,
            publisher=input_.publisher,
            published_at=input_.published_at,
            retrieved_at=input_.retrieved_at,
            excerpt=input_.excerpt,
            query=input_.query,
            content_hash=content_hash,
            confidence=input_.confidence,
            metadata_json=input_.metadata,
        )
        db.add(evidence)
        await db.flush()
        logger.info("Evidence: stored id=%d hash=%s", evidence.id, content_hash[:16])
        return evidence

    async def list_by_task(
        self, db: AsyncSession, task_id: str
    ) -> list[ResearchEvidence]:
        """获取任务的所有证据

        参数:
            db: 异步数据库会话
            task_id: 研究任务 ID

        返回:
            list[ResearchEvidence]: 按创建时间升序排列的证据列表
        """
        result = await db.execute(
            select(ResearchEvidence)
            .where(ResearchEvidence.task_id == task_id)
            .order_by(ResearchEvidence.created_at)
        )
        return list(result.scalars().all())
