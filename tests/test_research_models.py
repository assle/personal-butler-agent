"""
研究任务 ORM 测试
验证研究任务、报告、投递、群权限和企微用户绑定表已注册。
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
