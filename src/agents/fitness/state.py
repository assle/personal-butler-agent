from typing import TypedDict, Optional


class FitnessState(TypedDict, total=False):
    intent: str
    message: str
    user_id: str
    raw_result: Optional[str]
    parsed_items: list[dict]
    saved_records: list[dict]
    history_text: str
    preferences: dict
    reply: str
    data: Optional[dict]
    error: Optional[str]
