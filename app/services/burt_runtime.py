from uuid import uuid4

import config
from app.schemas.sessions import ConversationTurnResponse
from app.services.session_store import create_session_record
from burt import (
    BugAgentState,
    build_burt_graph,
    gen_report,
    ingest_user_description,
    initialize_runtime,
    load_initial_message,
)


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


def start_conversation(bug_id: int, description_level: str) -> ConversationTurnResponse:
    from langgraph.checkpoint.redis import RedisSaver

    session_id = str(uuid4())
    initial_message = load_initial_message(
        current_bug=bug_id,
        description_level=description_level,
    )
    app_graph, app_name, screen_descriptions = initialize_runtime(
        current_bug=bug_id,
        description_level=description_level,
    )

    runnable_config = {
        "configurable": {
            "app_graph": app_graph,
            "app_name": app_name,
            "screen_descriptions": screen_descriptions,
            "thread_id": session_id,
        }
    }
    initial_state_update = ingest_user_description(initial_message)
    state = BugAgentState(messages=[initial_state_update["messages"]])

    with RedisSaver.from_conn_string(config.REDIS_URL) as checkpointer:
        checkpointer.setup()
        graph = build_burt_graph(checkpointer)
        result = graph.invoke(state, config=runnable_config)

    if "__interrupt__" in result:
        response = ConversationTurnResponse(
            session_id=session_id,
            status="awaiting_user",
            question=_extract_follow_up_question(result["__interrupt__"]),
            final_report=None,
        )
        create_session_record(
            {
                "session_id": session_id,
                "bug_id": bug_id,
                "description_level": description_level,
                **response.model_dump(mode="json"),
            }
        )
        return response

    final_report = gen_report(result["BugInfo"], app_graph=app_graph, app_name=app_name)
    response = ConversationTurnResponse(
        session_id=session_id,
        status="completed",
        question=None,
        final_report=final_report,
    )
    create_session_record(
        {
            "session_id": session_id,
            "bug_id": bug_id,
            "description_level": description_level,
            **response.model_dump(mode="json"),
        }
    )
    return response
