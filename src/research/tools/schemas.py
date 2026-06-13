"""研究工具定义与执行合约"""
from typing import Literal
from pydantic import BaseModel, Field


class ToolExecutionContext(BaseModel):
    """工具执行上下文"""
    workspace_id: str
    user_id: str
    task_id: str
    step_id: str


class ToolExecutionResult(BaseModel):
    """工具执行结果"""
    success: bool
    data: dict = Field(default_factory=dict)
    error: str | None = None


class ResearchToolDefinition(BaseModel):
    """研究工具注册信息"""
    name: str
    description: str = ""
    risk_level: Literal["read", "internal_write", "external_action"] = "read"
    data_scope: Literal["user", "workspace", "public_web"] = "workspace"
    cost_class: Literal["low", "medium", "high"] = "low"
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_attempts: int = Field(default=3, ge=1, le=5)
    provider_name: str = "builtin"
    provider_version: str = "1"
