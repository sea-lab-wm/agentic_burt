from datetime import datetime

from pydantic import BaseModel

#The create_session endpoint recieves a request of this shape
class CreateSessionRequest(BaseModel):
    bug_id: int
    description_level: str

#The create_session endpoint responds to request sender with this shape
class SessionResponse(BaseModel):
    session_id: str
    bug_id: int
    description_level: str
    status: str
    created_at: datetime
