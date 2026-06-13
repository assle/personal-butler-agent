"""
工作空间模型测试
验证 Workspace 和 WorkspaceMember ORM 模型的表结构和约束定义

测试范围:
  - 表注册到 metadata
  - 唯一约束正确性
"""
from src.db.base import Base


def test_workspace_tables_are_registered():
    """验证工作空间与成员表注册到 metadata"""
    assert {"workspaces", "workspace_members"} <= set(Base.metadata.tables)


def test_workspace_membership_is_unique():
    """验证同一工作空间内用户身份唯一"""
    table = Base.metadata.tables["workspace_members"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if hasattr(constraint, "columns")
    }
    assert ("workspace_id", "open_userid") in unique_columns
