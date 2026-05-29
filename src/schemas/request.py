from datetime import datetime
from pydantic import BaseModel, Field


class DebugMessageRequest(BaseModel):
    user_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    timestamp: datetime | None = None
