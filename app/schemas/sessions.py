from typing import Any, Literal

from pydantic import BaseModel

#defines initial conversation/session start request payload
class CreateSessionRequest(BaseModel):
    bug_id: int
    description_level: str

#defines agent response to user input payload
#Contians either a follow up quesstion or generated report
class ConversationTurnResponse(BaseModel):
    session_id: str
    status: Literal["awaiting_user", "completed"]
    question: str | None = None
    final_report: dict[str, Any] | None = None
