from uuid import uuid4

import config
from app.schemas.sessions import ConversationTurnResponse
from app.services.session_store import create_session_record, get_session
from burt import (
    BugAgentState,
    build_burt_graph,
    gen_report,
    ingest_user_description,
    initialize_runtime,
    load_initial_message,
)
from langgraph.types import Command
from langgraph.checkpoint.redis import RedisSaver


class SessionNotFoundError(ValueError):
    """Raised when a requested conversation session cannot be found."""


class InvalidSessionError(ValueError):
    """Raised when persisted session metadata is incomplete or malformed."""


class SessionCompletedError(ValueError):
    """Raised when attempting to resume an already-completed session."""


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
    app_graph: str,
    app_name: str,
    screen_descriptions: str,
) -> dict:
    """Build the LangGraph runtime config used for both new and resumed sessions."""
    return {
        "configurable": {
            "app_graph": app_graph,
            "app_name": app_name,
            "screen_descriptions": screen_descriptions,
            "thread_id": session_id,
        }
    }


def _persist_and_build_response(
    *,
    session_id: str,
    bug_id: int,
    description_level: str,
    result: dict,
    app_graph: str,
    app_name: str,
) -> ConversationTurnResponse:
    """Convert a graph result into an API response and persist the updated agent conversation session state."""

    #extract the next user facing agent generated payload from the interrupt if present, or generate the final report
    if "__interrupt__" in result:
        response = ConversationTurnResponse(
            session_id=session_id,
            status="awaiting_user",
            question=_extract_follow_up_question(result["__interrupt__"]),
            final_report=None,
        )
    else:
        final_report = gen_report(result["BugInfo"], app_graph=app_graph, app_name=app_name)
        response = ConversationTurnResponse(
            session_id=session_id,
            status="completed",
            question=None,
            final_report=final_report,
        )

    #create a session record to track session meta data and most recent user facing generation for recovery
    create_session_record(
        {
            "session_id": session_id,
            "bug_id": bug_id,
            "description_level": description_level,
            **response.model_dump(mode="json"),
        }
    )
    return response


def start_conversation(bug_id: int, description_level: str) -> ConversationTurnResponse:
    """Create a new conversation session, run the first graph step, and save the outcome."""

    #create unique session id (uuid4() create a session id so unlikely to be already a duplicate that it can be treated as unique)
    session_id = str(uuid4())

    #load initial bug desc from dev set based on bug id and description level
    initial_message = load_initial_message(
        current_bug=bug_id,
        description_level=description_level,
    )

    #fetch graph data and initialize logger (logger currently offline!) 
    app_graph, app_name, screen_descriptions = initialize_runtime(
        current_bug=bug_id,
        description_level=description_level,
    )

    #build config so agent can fetch graph information to reason over
    runnable_config = _build_runnable_config(
        session_id=session_id,
        app_graph=app_graph,
        app_name=app_name,
        screen_descriptions=screen_descriptions,
    )

    #log first submitted description and use it to load initial LangGraph state
    initial_state_update = ingest_user_description(initial_message)
    state = BugAgentState(messages=[initial_state_update["messages"]])
    
    #setup redis checkpointer, build graph, invoke it, redis checkpointer automatically saves state and graph checkpoint at end of block
    with RedisSaver.from_conn_string(config.REDIS_URL) as checkpointer:
        checkpointer.setup()
        graph = build_burt_graph(checkpointer)
        result = graph.invoke(state, config=runnable_config)

    #create new session record based on graph output
    return _persist_and_build_response(
        session_id=session_id,
        bug_id=bug_id,
        description_level=description_level,
        result=result,
        app_graph=app_graph,
        app_name=app_name,
    )


def resume_conversation(user_description: str, session_id: str) -> ConversationTurnResponse:
    """Resume a saved conversation session from its latest checkpoint."""

    session_record = get_session(session_id)

    #check for missing session for curr session id
    if session_record is None:
        raise SessionNotFoundError(f"Session {session_id} was not found.")

    #check for already terminated session
    if session_record.get("status") == "completed":
        raise SessionCompletedError(f"Session {session_id} is already completed.")

    bug_id = session_record.get("bug_id")
    description_level = session_record.get("description_level")
    #check for malformed session
    if not isinstance(bug_id, int) or not isinstance(description_level, str):
        raise InvalidSessionError(
            f"Session {session_id} is missing required resume metadata."
        )

    #load initial bug desc from dev set based on bug id and description level
    app_graph, app_name, screen_descriptions = initialize_runtime(
        current_bug=bug_id,
        description_level=description_level,
    )

    #load initial bug desc from dev set based on bug id and description level
    runnable_config = _build_runnable_config(
        session_id=session_id,
        app_graph=app_graph,
        app_name=app_name,
        screen_descriptions=screen_descriptions,
    )

    #setup redis checkpointer, build graph, use redis checkpointer to init graph state at latest checkpoint, so invokation resumes from there, redis checkpointer automatically saves state and graph checkpoint at end of block
    with RedisSaver.from_conn_string(config.REDIS_URL) as checkpointer:
        checkpointer.setup()
        graph = build_burt_graph(checkpointer)
        result = graph.invoke(Command(resume=user_description), config=runnable_config)

    #create new session record based on graph output
    return _persist_and_build_response(
        session_id=session_id,
        bug_id=bug_id,
        description_level=description_level,
        result=result,
        app_graph=app_graph,
        app_name=app_name,
    )
