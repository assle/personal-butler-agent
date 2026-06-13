"""研究全链路追踪"""
from dataclasses import dataclass, field
import uuid

@dataclass(frozen=True)
class TraceContext:
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    workspace_id: str = ""
    task_id: str = ""
    step_id: str | None = None
    attempt: int | None = None

    def as_log_fields(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "attempt": self.attempt,
        }
