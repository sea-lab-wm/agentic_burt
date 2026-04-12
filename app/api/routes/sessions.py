from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from redis.exceptions import RedisError

from app.services.session_store import create_session_record, get_session, ping
from app.schemas.sessions import CreateSessionRequest, SessionResponse

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


@sessions_router.post("/sessions", response_model=SessionResponse)
def create_session(create_session_request: CreateSessionRequest) -> SessionResponse:
    session_response = SessionResponse(
        session_id=str(uuid4()),
        bug_id=create_session_request.bug_id,
        description_level=create_session_request.description_level,
        status="created",
        created_at=datetime.now(timezone.utc),
    )
    create_session_record(session_response.model_dump(mode="json"))
    return session_response


@sessions_router.get("/sessions/{session_id}", response_model=SessionResponse)
def recover_session(session_id: str) -> SessionResponse:
    session_record = get_session(session_id)
    if session_record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(**session_record)
