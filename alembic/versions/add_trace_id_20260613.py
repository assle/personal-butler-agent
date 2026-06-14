"""add trace_id to research_tasks and research_events

Revision ID: add_trace_id_20260613
Revises: e57f8e3d7981
Create Date: 2026-06-13 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "add_trace_id_20260613"
down_revision: Union[str, Sequence[str], None] = "e57f8e3d7981"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add nullable trace_id to research_tasks, backfill, then make non-null
    op.add_column(
        "research_tasks",
        sa.Column("trace_id", sa.String(32), nullable=True),
    )
    op.execute("UPDATE research_tasks SET trace_id = substr(replace(hex(randomblob(16)),'',''),1,16) WHERE trace_id IS NULL")
    op.alter_column("research_tasks", "trace_id", nullable=False)
    op.create_index(
        op.f("ix_research_tasks_trace_id"), "research_tasks", ["trace_id"], unique=False
    )

    # Add nullable trace_id to research_events, backfill, then make non-null
    op.add_column(
        "research_events",
        sa.Column("trace_id", sa.String(32), nullable=True),
    )
    op.execute("UPDATE research_events SET trace_id = '' WHERE trace_id IS NULL")
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
