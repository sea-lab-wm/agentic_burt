from fastapi import APIRouter, HTTPException
from redis.exceptions import RedisError

from app.schemas.sessions import ConversationTurnResponse, CreateSessionRequest
from app.services.burt_runtime import start_conversation
from app.services.session_store import get_session, ping

sessions_router = APIRouter()


@sessions_router.get("/healthz")
def healthz() -> dict[str, str | bool]:
    try:
        redis_ok = ping()
    except RedisError:
        redis_ok = False

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
    }


@sessions_router.post("/sessions", response_model=ConversationTurnResponse)
def create_session(create_session_request: CreateSessionRequest) -> ConversationTurnResponse:
    return start_conversation(
        bug_id=create_session_request.bug_id,
        description_level=create_session_request.description_level,
    )


@sessions_router.get("/sessions/{session_id}", response_model=ConversationTurnResponse)
def recover_session(session_id: str) -> ConversationTurnResponse:
    session_record = get_session(session_id)
    if session_record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return ConversationTurnResponse(**session_record)
