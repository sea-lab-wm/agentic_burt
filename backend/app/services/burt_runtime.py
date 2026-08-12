import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import config
from app.schemas.sessions import ConversationTurnResponse
from app.services.session_store import (
    acquire_session_lock,
    create_session_record,
    get_session,
    release_session_lock,
    redis_client,
)
from burt_core.burt import (
    BugAgentState,
    _flush_active_turn,
    build_burt_graph,
    create_runtime_context,
    ingest_user_description,
    load_bug_graph_context,
)
from langgraph.types import Command
from langgraph.checkpoint.redis import RedisSaver
from observability.observability_sinks import LocalFileSink

logger = logging.getLogger(__name__)


class SessionNotFoundError(ValueError):
    """Raised when a requested conversation session cannot be found."""


class InvalidSessionError(ValueError):
    """Raised when persisted session metadata is incomplete or malformed."""


class SessionCompletedError(ValueError):
    """Raised when attempting to resume an already-completed session."""


class SessionLockedError(ValueError):
    """Raised when a conversation session is already being resumed elsewhere."""


class ReportEditLimitError(ValueError):
    """Raised when a session has already used all of its report regenerations."""


def _extract_follow_up_question(interrupt_payload) -> str | None:
    """Pull the human-facing follow-up question out of a LangGraph interrupt payload."""
    payload = interrupt_payload
    if isinstance(payload, (list, tuple)) and payload:
        payload = payload[0]
    if hasattr(payload, "value"):
        payload = payload.value
    if isinstance(payload, dict):
        return payload.get("Follow Up Question")
    return None


def _build_runnable_config(
    session_id: str,
    transitions: str,
    app_name: str,
    screen_descriptions: str,
    runtime_context,
) -> dict:
    """Build the LangGraph runtime config used for both new and resumed sessions."""
    return {
        "configurable": {
            "transitions": transitions,
            "app_name": app_name,
            "screen_descriptions": screen_descriptions,
            "thread_id": session_id,
            "runtime_context": runtime_context,
        }
    }


def report_revisions(session_record: dict) -> tuple[int, int]:
    """Read how many draft reports and saved edits a session already has on file."""
    draft_revision = session_record.get("draft_revision")
    final_revision = session_record.get("final_revision")

    return (
        draft_revision if isinstance(draft_revision, int) else 0,
        final_revision if isinstance(final_revision, int) else 0,
    )


def _edits_remaining(final_revision: int) -> int:
    """Return how many more edit-and-regenerate rounds a session may still run."""
    return max(config.MAX_REPORT_EDITS - final_revision, 0)


def _persist_and_build_response(
    *,
    session_id: str,
    bug_id: int,
    result: dict,
    runtime_context,
    draft_revision: int = 0,
    final_revision: int = 0,
) -> ConversationTurnResponse:
    """Convert a graph result into an API response and persist the updated agent conversation session state.

    ``draft_revision`` and ``final_revision`` count the reports already on file
    before this run; a run that reaches a report writes the next draft revision.
    """

    #extract the next user facing agent generated payload from the interrupt if present, or generate the final report
    if "__interrupt__" in result:
        response = ConversationTurnResponse(
            session_id=session_id,
            status="awaiting_user",
            question=_extract_follow_up_question(result["__interrupt__"]),
            final_report=None,
            draft_revision=draft_revision,
            final_revision=final_revision,
            edits_remaining=_edits_remaining(final_revision),
        )
    else:
        #fetch full report from last LangGraph execution payload to populate the full_report record at the end of the logs
        final_report = result.get("full_report")
        if not isinstance(final_report, dict):
            raise ValueError("Completed graph result is missing a valid full_report payload.")
        draft_revision += 1
        response = ConversationTurnResponse(
            session_id=session_id,
            status="completed",
            question=None,
            final_report=final_report,
            draft_revision=draft_revision,
            final_revision=final_revision,
            edits_remaining=_edits_remaining(final_revision),
        )
        runtime_context.sink.finalize_session(
            session_id=session_id,
            final_report=final_report,
            run_metadata={
                "bug_id": bug_id,
                "description_level": None,
                "input_source": "user",
                "runtime": "api",
            },
            revision=draft_revision,
        )

    #create a session record to track session meta data and most recent user facing generation for recovery
    create_session_record(
        {
            "session_id": session_id,
            "bug_id": bug_id,
            **response.model_dump(mode="json"),
        }
    )

    if response.status == "completed":
        try:
            with RedisSaver.from_conn_string(config.REDIS_URL) as checkpointer:
                checkpointer.setup()
                checkpointer.delete_thread(session_id)
        except Exception:
            #emit log record on failiure, but still return gen. report payload
            logger.warning(
                "Failed to delete LangGraph checkpoints for completed session %s.",session_id,exc_info=True)

    return response


def build_api_log_path(session_id: str) -> Path:
    """Build the log path used for one containerized API session."""
    return Path("logs") / str(config.PROMPT_VERSION) / f"{session_id}.log"


def format_report_as_description(report: dict[str, Any]) -> str:
    """Flatten a saved report back into the plain bug description BURT++ reads.

    A regeneration re-enters the graph through the same door a typed message does,
    so the user's corrections have to arrive as prose rather than as a report shape.
    """
    lines: list[str] = []

    for key, value in report.items():
        label = str(key).replace("_", " ").strip().title()

        if isinstance(value, (list, tuple)):
            body = "\n".join(f"- {item}" for item in value)
            lines.append(f"{label}:\n{body}" if body else f"{label}:")
        elif isinstance(value, dict):
            lines.append(f"{label}: {json.dumps(value)}")
        else:
            lines.append(f"{label}: {value}")

    return (
        "I corrected the bug report you generated. Treat the corrected report below "
        "as my description of the bug and regenerate the report from it.\n\n"
        + "\n\n".join(lines)
    )


def _run_conversation_from_description(
    *,
    session_id: str,
    bug_id: int,
    user_description: str,
    draft_revision: int = 0,
    final_revision: int = 0,
    reset_thread: bool = False,
    single_pass: bool = False,
) -> ConversationTurnResponse:
    """Run BURT++ from the start on one description and persist the outcome.

    This is the path a first message takes, and the one a regeneration reuses so a
    saved edit re-enters the graph exactly the way a typed message would.

    ``single_pass`` suppresses the follow-up loop, so the run always comes back
    with a report rather than with a question.
    """

    #fetch graph data and initialize logger
    transitions, app_name, screen_descriptions = load_bug_graph_context(
        current_bug=bug_id
    )
    runtime_context = create_runtime_context(
        session_id=session_id,
        log_path=build_api_log_path(session_id),
        sink_mode="redis_then_file",
        redis_client=redis_client,
    )

    #build config so agent can fetch graph information to reason over
    runnable_config = _build_runnable_config(
        session_id=session_id,
        transitions=transitions,
        app_name=app_name,
        screen_descriptions=screen_descriptions,
        runtime_context=runtime_context,
    )

    #log the submitted description and use it to load initial LangGraph state
    initial_state_update = ingest_user_description(
        user_description,
        runtime_context=runtime_context,
    )
    state = BugAgentState(
        messages=[initial_state_update["messages"]],
        single_pass=single_pass,
    )

    #setup redis checkpointer, build graph, invoke it, redis checkpointer automatically saves state and graph checkpoint at end of block
    with RedisSaver.from_conn_string(config.REDIS_URL) as checkpointer:
        checkpointer.setup()
        #a regenerated run reuses the thread id of the run it replaces, so any
        #checkpoint the previous run failed to clear would resume it instead
        if reset_thread:
            checkpointer.delete_thread(session_id)
        graph = build_burt_graph(checkpointer)
        result = graph.invoke(state, config=runnable_config)
    _flush_active_turn(runtime_context)

    #create new session record based on graph output
    return _persist_and_build_response(
        session_id=session_id,
        bug_id=bug_id,
        result=result,
        runtime_context=runtime_context,
        draft_revision=draft_revision,
        final_revision=final_revision,
    )


def save_modified_report(
    *,
    session_id: str,
    modified_report: dict,
) -> ConversationTurnResponse:
    """Log a user-edited report, then rerun BURT++ to regenerate from the edit.

    The edit is kept as "final report N" and the run it seeds produces the next
    draft report, up to ``config.MAX_REPORT_EDITS`` rounds per session.

    The rerun is single-pass: the user has already said what they wanted changed,
    so it regenerates in one try rather than asking anything back.
    """
    #the rerun invokes the graph, so it takes the same lock a resume does
    lock_token = acquire_session_lock(session_id)
    if lock_token is None:
        raise SessionLockedError("Session is already being resumed. Retry shortly.")

    try:
        session_record = get_session(session_id)
        if session_record is None:
            raise SessionNotFoundError(f"Session {session_id} was not found.")

        if session_record.get("status") != "completed":
            raise SessionCompletedError(
                f"Session {session_id} must be completed before editing its report."
            )

        bug_id = session_record.get("bug_id")
        if not isinstance(bug_id, int):
            raise InvalidSessionError(
                f"Session {session_id} is missing required report metadata."
            )

        draft_revision, final_revision = report_revisions(session_record)
        if final_revision >= config.MAX_REPORT_EDITS:
            raise ReportEditLimitError(
                f"Session {session_id} has already used its "
                f"{config.MAX_REPORT_EDITS} report regenerations."
            )

        final_revision += 1
        LocalFileSink(filepath=build_api_log_path(session_id)).append_modified_report(
            session_id=session_id,
            modified_report=modified_report,
            revision=final_revision,
        )

        #bank the edit before the rerun, so a failed regeneration still spends the
        #round it was given rather than letting the same edit be replayed
        create_session_record(
            {
                **session_record,
                "bug_id": bug_id,
                "final_report": modified_report,
                "modified_report": modified_report,
                "draft_revision": draft_revision,
                "final_revision": final_revision,
                "edits_remaining": _edits_remaining(final_revision),
            }
        )

        return _run_conversation_from_description(
            session_id=session_id,
            bug_id=bug_id,
            user_description=format_report_as_description(modified_report),
            draft_revision=draft_revision,
            final_revision=final_revision,
            reset_thread=True,
            single_pass=True,
        )
    finally:
        release_session_lock(session_id, lock_token)


def start_conversation(bug_id: int, user_description: str) -> ConversationTurnResponse:
    """Create a new conversation session, run the first graph step, and save the outcome."""

    #create unique session id (uuid4() create a session id so unlikely to be already a duplicate that it can be treated as unique)
    session_id = str(uuid4())

    return _run_conversation_from_description(
        session_id=session_id,
        bug_id=bug_id,
        user_description=user_description,
    )


def resume_conversation(user_description: str, session_id: str) -> ConversationTurnResponse:
    """Resume a saved conversation session from its latest checkpoint."""

    #attempt to acquire the session lock
    lock_token = acquire_session_lock(session_id)
    if lock_token is None:
        #if not acquirable, session is already being resumed
        raise SessionLockedError("Session is already being resumed. Retry shortly.")

    try:
        #try to run the critical operations of resume_conversation

        #acquire the session_record so that the meta data it tracks about the session being resumed can be updated following agent invokation. 
        session_record = get_session(session_id)

        #check for missing session for curr session id
        if session_record is None:
            raise SessionNotFoundError(f"Session {session_id} was not found.")

        #check for already terminated session
        if session_record.get("status") == "completed":
            raise SessionCompletedError(f"Session {session_id} is already completed.")

        bug_id = session_record.get("bug_id")
        #check for malformed session
        if not isinstance(bug_id, int):
            raise InvalidSessionError(
                f"Session {session_id} is missing required resume metadata."
            )

        #a resumed run belongs to the revision round that is already under way
        draft_revision, final_revision = report_revisions(session_record)

        #load initial bug desc from dev set based on bug id and description level
        transitions, app_name, screen_descriptions = load_bug_graph_context(
            current_bug=bug_id
        )
        runtime_context = create_runtime_context(
            session_id=session_id,
            log_path=build_api_log_path(session_id),
            sink_mode="redis_then_file",
            redis_client=redis_client,
        )

        #load initial bug desc from dev set based on bug id and description level
        runnable_config = _build_runnable_config(
            session_id=session_id,
            transitions=transitions,
            app_name=app_name,
            screen_descriptions=screen_descriptions,
            runtime_context=runtime_context,
        )

        #setup redis checkpointer, build graph, use redis checkpointer to init graph state at latest checkpoint, so invokation resumes from there, redis checkpointer automatically saves state and graph checkpoint at end of block
        with RedisSaver.from_conn_string(config.REDIS_URL) as checkpointer:
            checkpointer.setup()
            graph = build_burt_graph(checkpointer)
            result = graph.invoke(Command(resume=user_description), config=runnable_config)
        _flush_active_turn(runtime_context)

        #create new session record based on graph output
        return _persist_and_build_response(
            session_id=session_id,
            bug_id=bug_id,
            result=result,
            runtime_context=runtime_context,
            draft_revision=draft_revision,
            final_revision=final_revision,
        )
    finally:
        #release the session lock on error or on sucessful completion of resume_converation critical section
        release_session_lock(session_id, lock_token)
