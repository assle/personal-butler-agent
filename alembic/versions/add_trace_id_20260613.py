"""add trace_id to research_tasks and research_events

Revision ID: add_trace_id_20260613
Revises: e57f8e3d7981
Create Date: 2026-06-13 22:30:00.000000

"""

"""
修复历史 trace_id 回填。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_trace_id_20260613"
down_revision: Union[str, Sequence[str], None] = "e57f8e3d7981"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_task_trace_ids() -> None:
    """按数据库方言回填任务追踪标识；无参数，无返回值"""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            UPDATE research_tasks
            SET trace_id = substr(md5(id), 1, 16)
            WHERE trace_id IS NULL OR trace_id = ''
            """
        )
        return
    op.execute(
        """
        UPDATE research_tasks
        SET trace_id = lower(substr(hex(randomblob(16)), 1, 16))
        WHERE trace_id IS NULL OR trace_id = ''
        """
    )


def _backfill_event_trace_ids() -> None:
    """从所属任务回填事件追踪标识；无参数，无返回值"""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            UPDATE research_events AS event
            SET trace_id = task.trace_id
            FROM research_tasks AS task
            WHERE event.task_id = task.id
              AND (event.trace_id IS NULL OR event.trace_id = '')
            """
        )
        return
    op.execute(
        """
        UPDATE research_events
        SET trace_id = (
            SELECT research_tasks.trace_id
            FROM research_tasks
            WHERE research_tasks.id = research_events.task_id
        )
        WHERE trace_id IS NULL OR trace_id = ''
        """
    )


def upgrade() -> None:
    """Upgrade schema."""
    # Add nullable trace_id to research_tasks, backfill, then make non-null
    op.add_column(
        "research_tasks",
        sa.Column("trace_id", sa.String(32), nullable=True),
    )
    _backfill_task_trace_ids()
    op.alter_column("research_tasks", "trace_id", nullable=False)
    op.create_index(
        op.f("ix_research_tasks_trace_id"), "research_tasks", ["trace_id"], unique=False
    )

    # Add nullable trace_id to research_events, backfill, then make non-null
    op.add_column(
        "research_events",
        sa.Column("trace_id", sa.String(32), nullable=True),
    )
    _backfill_event_trace_ids()
    op.alter_column("research_events", "trace_id", nullable=False)
    op.create_index(
        op.f("ix_research_events_trace_id"), "research_events", ["trace_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_research_events_trace_id"), table_name="research_events")
    op.drop_column("research_events", "trace_id")
    op.drop_index(op.f("ix_research_tasks_trace_id"), table_name="research_tasks")
    op.drop_column("research_tasks", "trace_id")
