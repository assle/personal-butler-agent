"""修复智能机器人入站消息时间戳的 PostgreSQL 时区类型。

Workflow:
1. 检查 inbound_messages 当前时间列类型。
2. 将无时区时间按 UTC 解释并转换为 TIMESTAMP WITH TIME ZONE。
3. SQLite 不执行物理类型变更，因为其 DateTime 不区分时区类型。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fix_inbound_tz_20260614"
down_revision: Union[str, Sequence[str], None] = "repair_trace_id_20260614"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timezone_columns() -> dict[str, bool]:
    """读取入站时间列是否带时区；无输入参数；返回列名到时区状态的映射。"""
    inspector = sa.inspect(op.get_bind())
    return {
        column["name"]: bool(getattr(column["type"], "timezone", False))
        for column in inspector.get_columns("inbound_messages")
        if column["name"] in {"received_at", "processed_at"}
    }


def upgrade() -> None:
    """将入站 UTC 时间列升级为带时区类型；无输入参数；无返回值。"""
    if op.get_bind().dialect.name != "postgresql":
        return

    timezone_columns = _timezone_columns()
    if not timezone_columns.get("received_at", False):
        op.alter_column(
            "inbound_messages",
            "received_at",
            existing_type=sa.DateTime(timezone=False),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
            postgresql_using="received_at AT TIME ZONE 'UTC'",
        )
    if not timezone_columns.get("processed_at", False):
        op.alter_column(
            "inbound_messages",
            "processed_at",
            existing_type=sa.DateTime(timezone=False),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
            postgresql_using="processed_at AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    """将入站时间列降级为 UTC 无时区类型；无输入参数；无返回值。"""
    if op.get_bind().dialect.name != "postgresql":
        return

    timezone_columns = _timezone_columns()
    if timezone_columns.get("received_at", False):
        op.alter_column(
            "inbound_messages",
            "received_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(timezone=False),
            existing_nullable=False,
            postgresql_using="received_at AT TIME ZONE 'UTC'",
        )
    if timezone_columns.get("processed_at", False):
        op.alter_column(
            "inbound_messages",
            "processed_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(timezone=False),
            existing_nullable=True,
            postgresql_using="processed_at AT TIME ZONE 'UTC'",
        )
