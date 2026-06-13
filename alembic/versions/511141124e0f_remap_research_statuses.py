"""remap research statuses

Revision ID: 511141124e0f
Revises: 20260613_0001
Create Date: 2026-06-13 20:09:12.178103

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '511141124e0f'
down_revision: Union[str, Sequence[str], None] = '20260613_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "UPDATE research_tasks SET status = 'submitted' WHERE status = 'queued'"
    )
    op.execute(
        "UPDATE research_tasks SET status = 'failed' WHERE status = 'timed_out'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "UPDATE research_tasks SET status = 'queued' WHERE status = 'submitted'"
    )
    op.execute(
        "UPDATE research_tasks SET status = 'timed_out' WHERE status = 'failed'"
    )
