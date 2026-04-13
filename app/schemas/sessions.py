from typing import Any, Literal

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    bug_id: int
    description_level: str


class ResumeConversationRequest(BaseModel):
    user_description: str


class ConversationTurnResponse(BaseModel):
    session_id: str
    status: Literal["awaiting_user", "completed"]
    question: str | None = None
    final_report: dict[str, Any] | None = None
