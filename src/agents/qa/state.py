from typing import TypedDict, Optional


class QAState(TypedDict, total=False):
    intent: str
    message: str
    user_id: str
    preferences: dict
    reply: str
    error: Optional[str]
