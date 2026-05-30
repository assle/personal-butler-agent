from typing import TypedDict, Optional


class SummaryState(TypedDict, total=False):
    intent: str
    message: str
    user_id: str
    reply: str
    error: Optional[str]
