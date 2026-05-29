from dataclasses import dataclass, field
from pydantic import BaseModel


@dataclass
class AgentResponse:
    reply: str
    data: dict | None = None


class DebugMessageResponse(BaseModel):
    intent: str
    confidence: float
    response: str
    data: dict | None = None
