"""
对话记忆管理
提供对话上下文获取、交换保存和自动压缩功能

在总流程中的位置:
  agent.handle() → ConversationMemory.get_context(user_id, db)
  → graph.ainvoke() → ConversationMemory.save_exchange(user_id, user_msg, reply, db)
  → _maybe_compress() 自动触发旧消息压缩

Workflow:
  1. get_context: 从 summaries 表取摘要 + 从 messages 表取最近12条
  2. save_exchange: 写入两条消息，超过24条时触发压缩
  3. _compress: 取最早12条 + 现有摘要 → LLM 生成新摘要 → upsert summaries + 删除旧消息
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, select

from src.models.conversation import ConversationMessage, ConversationSummary

logger = logging.getLogger(__name__)

MAX_MESSAGES = 24
WINDOW_SIZE = 12
COMPRESS_BATCH = 12

COMPRESS_PROMPT = """你是对话摘要器。把以下对话历史和之前的摘要压缩成一句简短摘要（不超过80字），
保留关键事实和偏好信息。

之前的摘要：{existing_summary}

最新对话：
{old_messages}

只输出摘要文本，不要多余的话。"""


class ConversationMemory:
    """对话记忆管理器，负责读写对话历史和自动压缩"""

    def __init__(self, llm_client):
        """初始化对话记忆管理器

        参数:
            llm_client: LLMClient 实例，用于生成摘要
        """
        self._llm = llm_client

    async def get_context(self, user_id: str, db) -> tuple[str | None, list[dict]]:
        """获取用户对话上下文（摘要 + 最近消息）

        参数:
            user_id: 用户标识
            db: SQLAlchemy 异步会话

        返回:
            tuple[str|None, list[dict]]: (摘要文本或None, 最近消息列表)
        """
        try:
            summary_result = await db.execute(
                select(ConversationSummary).where(
                    ConversationSummary.user_id == user_id
                )
            )
            summary_row = summary_result.scalar_one_or_none()
            summary = summary_row.summary_text if summary_row else None

            messages_result = await db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.user_id == user_id)
                .order_by(ConversationMessage.created_at.desc())
                .limit(WINDOW_SIZE)
            )
            recent = list(reversed(messages_result.scalars().all()))

            recent_dicts = [
                {"role": msg.role, "content": msg.content}
                for msg in recent
            ]
            return summary, recent_dicts
        except Exception:
            logger.exception("ConversationMemory.get_context failed for user=%s", user_id)
            return None, []

    async def save_exchange(
        self, user_id: str, user_msg: str, assistant_msg: str, db
    ) -> None:
        """保存一轮对话交换（用户消息 + 助手回复）

        参数:
            user_id: 用户标识
            user_msg: 用户消息文本
            assistant_msg: 助手回复文本
            db: SQLAlchemy 异步会话
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            db.add(ConversationMessage(
                user_id=user_id, role="user",
                content=user_msg, created_at=now,
            ))
            db.add(ConversationMessage(
                user_id=user_id, role="assistant",
                content=assistant_msg, created_at=now,
            ))
            await db.flush()

            await self._maybe_compress(user_id, db)
        except Exception:
            logger.exception("ConversationMemory.save_exchange failed for user=%s", user_id)

    async def _maybe_compress(self, user_id: str, db) -> None:
        """检查消息数是否需要压缩，超过阈值时触发

        参数:
            user_id: 用户标识
            db: SQLAlchemy 异步会话
        """
        try:
            count_result = await db.execute(
                select(func.count())
                .select_from(ConversationMessage)
                .where(ConversationMessage.user_id == user_id)
            )
            total = count_result.scalar()
            if total <= MAX_MESSAGES:
                return

            old_result = await db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.user_id == user_id)
                .order_by(ConversationMessage.created_at.asc())
                .limit(COMPRESS_BATCH)
            )
            old_messages = old_result.scalars().all()
            if not old_messages:
                return

            old_text = "\n".join(
                f"[{m.role}]: {m.content}" for m in old_messages
            )

            summary_result = await db.execute(
                select(ConversationSummary).where(
                    ConversationSummary.user_id == user_id
                )
            )
            summary_row = summary_result.scalar_one_or_none()
            existing = summary_row.summary_text if summary_row else "（无之前的摘要）"

            prompt = COMPRESS_PROMPT.format(
                existing_summary=existing,
                old_messages=old_text,
            )
            new_summary = await self._llm.chat(
                messages=[
                    {"role": "system", "content": "你是对话摘要器，输出简洁准确。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            new_summary = new_summary.strip()

            if not new_summary:
                return

            now = datetime.now(timezone.utc).isoformat()
            if summary_row:
                summary_row.summary_text = new_summary
                summary_row.last_summarized_at = now
            else:
                db.add(ConversationSummary(
                    user_id=user_id,
                    summary_text=new_summary,
                    last_summarized_at=now,
                ))
            await db.flush()

            old_ids = [m.id for m in old_messages]
            await db.execute(
                delete(ConversationMessage).where(
                    ConversationMessage.id.in_(old_ids)
                )
            )
            await db.flush()
        except Exception:
            logger.exception("ConversationMemory._compress failed for user=%s", user_id)
