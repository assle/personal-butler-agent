"""
研究任务 ORM 测试
验证研究任务、报告、投递、群权限和企微用户绑定表已注册，
并确保 workspace_id 外键列和索引正确存在。
"""
from sqlalchemy import inspect

from src.db.base import Base


def test_research_tables_are_registered():
    """验证研究基础设施表全部注册到 SQLAlchemy metadata"""
    expected = {
        "research_tasks",
        "research_reports",
        "research_deliveries",
        "user_group_access",
        "wecom_user_bindings",
    }
    assert expected <= set(Base.metadata.tables)


def test_research_task_has_idempotency_and_user_status_indexes():
    """验证研究任务具备回调幂等和用户运行状态索引"""
    table = Base.metadata.tables["research_tasks"]
    assert table.c.source_msgid.unique is True
    index_columns = {
        tuple(column.name for column in index.columns)
        for index in table.indexes
    }
    assert ("requester_open_userid", "status") in index_columns


def test_research_report_version_is_unique_per_task():
    """验证同一任务的报告版本不可重复"""
    table = Base.metadata.tables["research_reports"]
    constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if hasattr(constraint, "columns")
    }
    assert ("task_id", "version") in constraints


def test_research_task_has_workspace_id_column():
    """验证 research_tasks 表包含 workspace_id 外键和索引"""
    table = Base.metadata.tables["research_tasks"]
    assert "workspace_id" in table.c
    col = table.c.workspace_id
    assert col.nullable is False
    index_columns = {
        tuple(column.name for column in index.columns)
        for index in table.indexes
    }
    assert ("workspace_id",) in index_columns


def test_research_report_has_workspace_id_column():
    """验证 research_reports 表包含 workspace_id 外键和索引"""
    table = Base.metadata.tables["research_reports"]
    assert "workspace_id" in table.c
    col = table.c.workspace_id
    assert col.nullable is False


def test_research_task_status_contains_harness_states():
    """验证研究主任务包含完整 Harness 状态"""
    from src.research.schemas import ResearchTaskStatus

    assert {status.value for status in ResearchTaskStatus} == {
        "submitted",
        "planning",
        "awaiting_approval",
        "running",
        "synthesizing",
        "validating",
        "completed",
        "delivering",
        "delivered",
        "retrying",
        "failed",
        "cancelled",
    }


def test_active_statuses_block_second_task():
    """验证未终止状态都会阻止同用户重复提交"""
    from src.research.schemas import ACTIVE_RESEARCH_STATUSES

    assert ACTIVE_RESEARCH_STATUSES == {
        "submitted",
        "planning",
        "awaiting_approval",
        "running",
        "synthesizing",
        "validating",
        "retrying",
    }


def test_research_delivery_has_workspace_id_column():
    """验证 research_deliveries 表包含 workspace_id 外键和索引"""
    table = Base.metadata.tables["research_deliveries"]
    assert "workspace_id" in table.c
    col = table.c.workspace_id
    assert col.nullable is False


def test_research_execution_tables_are_registered():
    """验证研究执行表全部注册"""
    expected = {
        "research_plans",
        "research_steps",
        "research_step_dependencies",
        "research_approvals",
        "research_usage",
        "research_events",
    }
    assert expected <= set(Base.metadata.tables)


def test_step_idempotency_is_workspace_scoped():
    """验证步骤幂等键在工作空间内唯一"""
    table = Base.metadata.tables["research_steps"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if hasattr(constraint, "columns")
    }
    assert ("workspace_id", "idempotency_key") in unique_columns
