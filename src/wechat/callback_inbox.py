"""
智能机器人 URL 回调入站收件箱
负责将回调消息按 msgid 幂等写入 SQLite，并更新后台处理状态

Workflow:
1. record_inbound_message() 收到解析后的智能机器人消息体
2. 先查询 msgid 是否存在，存在则返回 should_process=False
3. 不存在则写入 pending 记录并 flush，HTTP 路由随后可立即返回成功
4. 后台任务调用 mark_processing/mark_processed/mark_failed 更新状态
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.inbound_message import InboundMessage


@dataclass(frozen=True)
class InboxRecordResult:
    """入站消息落库结果"""

    message: InboundMessage
    """入站消息 ORM 对象"""

    should_process: bool
    """是否应启动后台处理，重复消息为 False"""


async def record_inbound_message(db: AsyncSession, msg: dict) -> InboxRecordResult:
    """按 msgid 幂等记录一条智能机器人入站消息

    参数:
        db: SQLAlchemy 异步会话
        msg: 智能机器人消息体

    返回:
        InboxRecordResult: 已存在或新创建的消息记录，以及是否需要处理
    """
    msgid = msg.get("msgid", "")
    if not msgid:
        raise ValueError("aibot callback message missing msgid")
    existing = await _get_by_msgid(db, msgid)
    if existing is not None:
        return InboxRecordResult(message=existing, should_process=False)

    row = InboundMessage(
        msgid=msgid,
        source="aibot_callback",
        status="pending",
        payload_json=json.dumps(msg, ensure_ascii=False),
        response_url=msg.get("response_url"),
    )
    db.add(row)
    await db.flush()
    return InboxRecordResult(message=row, should_process=True)


async def mark_processing(db: AsyncSession, msgid: str):
    """标记消息开始处理

    参数:
        db: SQLAlchemy 异步会话
        msgid: 企业微信消息唯一 ID
    """
    row = await _get_by_msgid(db, msgid)
    if row is not None:
        row.status = "processing"
        row.attempts += 1
        row.error = None
        await db.flush()


async def mark_processed(db: AsyncSession, msgid: str):
    """标记消息处理成功

    参数:
        db: SQLAlchemy 异步会话
        msgid: 企业微信消息唯一 ID
    """
    row = await _get_by_msgid(db, msgid)
    if row is not None:
        row.status = "processed"
        row.processed_at = datetime.now(timezone.utc)
        row.error = None
        await db.flush()


async def mark_failed(db: AsyncSession, msgid: str, error: str):
    """标记消息处理失败

    参数:
        db: SQLAlchemy 异步会话
        msgid: 企业微信消息唯一 ID
        error: 失败原因
    """
    row = await _get_by_msgid(db, msgid)
    if row is not None:
        row.status = "failed"
        row.processed_at = datetime.now(timezone.utc)
        row.error = error[:1000]
        await db.flush()


async def _get_by_msgid(db: AsyncSession, msgid: str) -> InboundMessage | None:
    """根据 msgid 查询入站消息

    参数:
        db: SQLAlchemy 异步会话
        msgid: 企业微信消息唯一 ID

    返回:
        InboundMessage | None: 找到则返回 ORM 对象
    """
    result = await db.execute(select(InboundMessage).where(InboundMessage.msgid == msgid))
    return result.scalar_one_or_none()
