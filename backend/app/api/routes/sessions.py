import logging

from fastapi import APIRouter, HTTPException
from redis.exceptions import RedisError

from app.schemas.sessions import (
    ActiveBugIdsResponse,
    ConversationTurnResponse,
    CreateSessionRequest,
    ModifyReportRequest,
    ResumeConversationRequest,
)
from app.services.burt_runtime import (
    InvalidSessionError,
    SessionCompletedError,
    SessionLockedError,
    SessionNotFoundError,
    resume_conversation,
    save_modified_report,
    start_conversation,
)
from app.services.session_store import get_session, ping
from gui_graph_context_management.loader import list_active_bug_ids

sessions_router = APIRouter()
logger = logging.getLogger(__name__)


@sessions_router.get("/healthz")
def healthz() -> dict[str, str | bool]:
    """Report API health and whether Redis client is currently reachable."""
    try:
        redis_ok = ping()
    except RedisError:
        redis_ok = False

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": redis_ok,
    }


@sessions_router.get("/bugs/active", response_model=ActiveBugIdsResponse)
def active_bugs() -> ActiveBugIdsResponse:
    """List bug ids whose GUI graph contexts are loadable by the runtime."""
    return ActiveBugIdsResponse(bug_ids=list_active_bug_ids())


@sessions_router.post("/sessions", response_model=ConversationTurnResponse)
def create_session(create_session_request: CreateSessionRequest) -> ConversationTurnResponse:
    """Start a new agent conversation for the requested bug and initial user description."""
    try:
        return start_conversation(
            bug_id=create_session_request.bug_id,
            user_description=create_session_request.user_description,
        )
    except Exception as exc:
        logger.exception(
            "Failed to start conversation for bug_id=%s.",
            create_session_request.bug_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start BURT++ conversation: {type(exc).__name__}",
        ) from exc


@sessions_router.get("/sessions/{session_id}", response_model=ConversationTurnResponse)
def recover_session(session_id: str) -> ConversationTurnResponse:
    """Fetch the latest persisted user facing state for an existing agent conversation by session id.
    The session id is available as a path parameter, it identifies what existing session the recover request is acting upon.
    """
    session_record = get_session(session_id)
    if session_record is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return ConversationTurnResponse(**session_record)

@sessions_router.post("/sessions/{session_id}/messages", response_model=ConversationTurnResponse)
def resume_session(
    session_id: str,
    resume_request: ResumeConversationRequest,
) -> ConversationTurnResponse:
    """Resume a paused conversation by submitting the user's next description.
    The session id is available as a path parameter, it identifies what existing session the resume request is acting upon.
    """
    try:
        return resume_conversation(
            user_description=resume_request.user_description,
            session_id=session_id,
        )
    #You can find descriptions of the custom errors below in burt_runtime.py
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionCompletedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidSessionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@sessions_router.post("/sessions/{session_id}/report", response_model=ConversationTurnResponse)
def modify_report(
    session_id: str,
    modify_request: ModifyReportRequest,
) -> ConversationTurnResponse:
    """Persist a user-edited final report for a completed conversation."""
    try:
        return save_modified_report(
            session_id=session_id,
            modified_report=modify_request.modified_report,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionCompletedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidSessionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
