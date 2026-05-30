from typing import TypedDict, Optional


class MealState(TypedDict, total=False):
    intent: str
    message: str
    user_id: str
    preferences: dict
    trained_today: bool
    reply: str
    data: Optional[dict]
    error: Optional[str]
