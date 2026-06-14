"""
修复历史 trace_id 回填。
"""

"""
Workflow:
1. 修复已应用旧迁移但任务 trace_id 为空的数据库。
2. 从研究任务同步事件 trace_id。
3. 保持 schema 不变，仅修复数据。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "repair_trace_id_20260614"
down_revision: Union[str, Sequence[str], None] = "add_trace_id_20260613"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """修复任务和事件追踪标识；无参数，无返回值"""
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            UPDATE research_tasks
            SET trace_id = substr(md5(id), 1, 16)
            WHERE trace_id IS NULL OR trace_id = ''
            """
        )
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
        UPDATE research_tasks
        SET trace_id = lower(substr(hex(randomblob(16)), 1, 16))
        WHERE trace_id IS NULL OR trace_id = ''
        """
    )
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


def downgrade() -> None:
    """数据修复迁移无需回滚；无参数，无返回值"""
    return None
