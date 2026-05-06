from dataclasses import dataclass
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import Literal
import redis
from .state import ActiveFollowUp, BugAgentState, FollowUpKind
from .agent_utils import llm_extract, llm_check_clarity, llm_clarity_follow_up, llm_map, format_extraction_update, find_unknown_or_ambiguous, format_unknown_or_ambiguous_references, llm_more_info_follow_up, generate_report
import config
from gui_graph_context_management.loader import fetch_graph_data
from observability.logging_runtime import (
    ObservabilityTokenCallback,
    TurnLogger,
    log_action,
)
from observability.observability_models import (
    ActionName,
    Entity,
)
from observability.observability_sinks import (
    LocalFileSink,
    ObservabilitySink,
    RedisThenFileSink,
)
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from pathlib import Path

#loading in environment variables
load_dotenv()

@dataclass
class BurtRuntimeContext:
    """Request-local runtime dependencies for one BURT conversation execution."""

    session_id: str
    logger: TurnLogger
    sink: ObservabilitySink
    usage_callback: ObservabilityTokenCallback
    model: ChatOpenAI

def create_runtime_context(
    session_id: str,
    log_path: Path | str,
    sink_mode: Literal["local", "redis_then_file"] = "local",
    redis_client: redis.Redis | None = None,
) -> BurtRuntimeContext:
    """Create the logger, callback, and model instances for one conversation request."""

    log_path = Path(log_path)

    if sink_mode == "local":
        sink = LocalFileSink(filepath=log_path)
    elif sink_mode == "redis_then_file":
        if redis_client is None:
            raise ValueError("redis_client is required when sink_mode is 'redis_then_file'.")
        sink = RedisThenFileSink(redis_client=redis_client, filepath=log_path)
    else:
        raise ValueError(f"Unsupported sink_mode: {sink_mode}")

    logger = TurnLogger(filepath=str(log_path), session_id=session_id, sink=sink)
    usage_callback = ObservabilityTokenCallback(logger=logger)
    model = ChatOpenAI(model=config.MODEL_NAME, callbacks=[usage_callback])
    
    return BurtRuntimeContext(
        session_id=session_id,
        logger=logger,
        sink=sink,
        usage_callback=usage_callback,
        model=model,
    )

def _get_runtime_context(config: RunnableConfig) -> BurtRuntimeContext:
    """Extract the request-local runtime context from LangGraph config."""
    runtime_context = (config.get("configurable") or {}).get("runtime_context")
    if runtime_context is None:
        raise ValueError("runtime_context is required in the LangGraph config.")
    return runtime_context

@log_action(entity=Entity.user, action_name=ActionName.user_description)
def ingest_user_description(
    user_text: str,
    runtime_context: BurtRuntimeContext,
) -> dict:
    """Wrap one user message as a LangChain ``HumanMessage`` state update."""
    return {"messages": HumanMessage(content=user_text)}

def load_bug_graph_context(current_bug: int) -> tuple[str, str, str]:
    """Fetch the transitions, app name, and screen descriptions for one bug."""
    transitions, app_name, screen_descriptions = fetch_graph_data(bug_id=current_bug)

    if not transitions or not app_name:
        raise ValueError(f"No transitions/app name found for bug ID {current_bug}.")
    return transitions, app_name, screen_descriptions

@log_action(entity=Entity.bot, action_name=ActionName.information_element_extraction)
def information_element_extraction(state: BugAgentState, config: RunnableConfig) -> dict:
    """Extract natural-language information elements from the active user window."""
    print("extracting information elements...\n")
    configurable = config.get("configurable") or {}
    app_name = configurable.get("app_name")
    runtime_context = _get_runtime_context(config)

    # Outside a clarification cycle, extract from the latest user message only.
    # During a clarification cycle, extract from the tracked message window.
    window_messages = state.messages[state.clarification_window_start_idx:]
    user_messages = [message.content for message in window_messages]

    active_follow_up = state.active_follow_up
    extraction_mode = "initial"
    follow_up_question = None
    target_info_elements = None

    if active_follow_up is not None:
        follow_up_question = active_follow_up.question
        if active_follow_up.kind == FollowUpKind.more_info:
            extraction_mode = "more_info_follow_up"
            target_info_elements = active_follow_up.target_info_elements
        else:
            extraction_mode = "clarity_follow_up"

    extraction = llm_extract(
        user_messages=user_messages,
        model=runtime_context.model,
        app_name=app_name,
        follow_up_question=follow_up_question,
        extraction_mode=extraction_mode,
        target_info_elements=target_info_elements,
    )
    
    #print(extraction)

    return {
        "information_element_extraction": extraction
    }

@log_action(entity=Entity.bot, action_name=ActionName.clarity_check)
def clarity_check(state: BugAgentState, config: RunnableConfig) -> dict:
    """Check whether the extracted information elements are clear enough to map."""
    print("checking clarity...\n")
    app_name = (config.get("configurable") or {}).get("app_name")
    runtime_context = _get_runtime_context(config)
    extracted_info = state.information_element_extraction
    clarity_result = llm_check_clarity(extracted_info, runtime_context.model, app_name)
    return {
        "clarity_route": clarity_result.clarity_route,
        "clarity_issues": clarity_result.clarity_issues,
    }

def should_route_clarity(state: BugAgentState):
    """Route one post-clarity step, allowing at most one clarification follow up if needed."""
    if state.clarification_rounds < 1:
        return state.clarity_route
    return "continue"

@log_action(entity=Entity.bot, action_name=ActionName.clarity_follow_up)
def clarity_follow_up(state: BugAgentState, config: RunnableConfig) -> dict:
    """Generate a follow-up question that resolves clarity issues."""
    print("following up on clarity issues...\n")
    app_name = (config.get("configurable") or {}).get("app_name")
    runtime_context = _get_runtime_context(config)
    clarity_issues = state.clarity_issues
    information_elements = state.information_element_extraction
    follow_up = llm_clarity_follow_up(
        information_elements, clarity_issues, runtime_context.model, app_name
    )
    return {
        "active_follow_up": ActiveFollowUp(
            kind=FollowUpKind.clarity,
            question=follow_up.follow_up_question,
            target_info_elements=[],
        ),
        "clarification_rounds": (state.clarification_rounds + 1),
    }

@log_action(entity=Entity.bot, action_name=ActionName.extract_and_update)
def map_to_graph(state : BugAgentState, config : RunnableConfig) -> dict:
    """Ground extracted information elements into the structured bug mapping."""
    print("mapping collected information to graph...\n")
    current_bug_info = state.BugInfo

    configurable = config.get("configurable") or {}
    transitions = configurable.get("transitions")
    app_name = configurable.get("app_name")
    screen_descriptions = configurable.get("screen_descriptions")
    runtime_context = _get_runtime_context(config)

    extracted_information_elements = state.information_element_extraction

    result = llm_map(
        current_bug_info=current_bug_info,
        transitions=transitions,
        screen_descriptions=screen_descriptions,
        extracted_information_elements=extracted_information_elements,
        model=runtime_context.model,
        app_name=app_name,
    )
    
    return format_extraction_update(state, result)

@log_action(entity=Entity.bot, action_name=ActionName.evaluate)
def evaluate_state(state : BugAgentState, config : RunnableConfig) -> dict:
    """
    Check if structured bug report mapping is complete. 
    If not complete flag any unknown or ambiguous bug-info slots that still need resolution.
    """
    print("evaluating collected information...\n")
    current_bug_info = state.BugInfo

    return {"unknown_and_low_confidence_info" : find_unknown_or_ambiguous(current_bug_info)}

def should_continue(state : BugAgentState):    
    """Route to another follow-up round or to final report generation, based on the presence of low confidence or missing mapping info."""
    if state.unknown_and_low_confidence_info:
        return "continue"
    return "end"

@log_action(entity=Entity.bot, action_name=ActionName.follow_up)
def more_info_follow_up(state : BugAgentState, config : RunnableConfig) -> dict:
    """Generate a follow-up question for unresolved bug-info fields."""
    print("following up on missing information...\n")
    current_bug_info = state.BugInfo

    configurable = config.get("configurable") or {}
    transitions = configurable.get("transitions")
    app_name = configurable.get("app_name")
    screen_descriptions = configurable.get("screen_descriptions")
    runtime_context = _get_runtime_context(config)

    formatted_unknown_and_low_confidence_info = format_unknown_or_ambiguous_references(
        current_bug_info,
        state.unknown_and_low_confidence_info,
    )

    follow_up = llm_more_info_follow_up(
        current_bug_info,
        transitions,
        screen_descriptions,
        formatted_unknown_and_low_confidence_info,
        runtime_context.model,
        app_name,
    )

    active_follow_up = ActiveFollowUp(
            kind=FollowUpKind.more_info,
            question=follow_up.follow_up_question,
            target_info_elements=follow_up.clarification_target_info_elements,
        )
    
    #print(active_follow_up)

    return {
        "active_follow_up": active_follow_up
    }

def interrupt_and_present(state : BugAgentState, config : RunnableConfig) -> dict:
    """Interrupt the graph, present the follow-up question, and ingest the reply."""
    question = state.active_follow_up.question if state.active_follow_up else None
    user_response = interrupt({"Follow Up Question": question})
    return ingest_user_description(
        user_response,
        runtime_context=_get_runtime_context(config),
    )

@log_action(entity=Entity.bot, action_name=ActionName.generate_report)
def generate_final_report(state: BugAgentState, config: RunnableConfig) -> dict:
    """Generate the final report as the terminal LangGraph step."""
    print("generating final bug report...\n")
    bug_info = state.BugInfo
    unresolved = find_unknown_or_ambiguous(bug_info)
    if unresolved:
        raise ValueError(
            f"Cannot generate report with unresolved bug info: {sorted(unresolved)}"
        )

    configurable = config.get("configurable") or {}
    transitions = configurable.get("transitions")
    app_name = configurable.get("app_name")
    runtime_context = _get_runtime_context(config)
    return generate_report(bug_info, transitions, runtime_context.model, app_name)

#NOTE: This name is a bit incomplete, it should eventually be something like persist_then_flush_turn
def _flush_active_turn(runtime_context: BurtRuntimeContext) -> None:
    """Persist the active turn, if one exists, and clear turn-local state."""

    #Beginning of flush marks end of turn lifecycle, mark the turn ended at here
    if runtime_context.logger.current_turn is not None:
        runtime_context.logger.current_turn.ended_at = datetime.now(timezone.utc).isoformat()

    turn_record = runtime_context.logger.build_turn_record()
    if turn_record is None:
        return
    runtime_context.sink.append_turn(turn_record)
    runtime_context.logger.reset_turn()

def build_burt_graph(checkpointer):
    """Build and compile the BURT workflow against the provided checkpointer."""
    burt_workflow = StateGraph(BugAgentState)
    burt_workflow.add_node("information_element_extraction", information_element_extraction)
    burt_workflow.add_node("clarity_check", clarity_check)
    burt_workflow.add_node("clarity_follow_up", clarity_follow_up)
    burt_workflow.add_node("map_to_graph", map_to_graph)
    burt_workflow.add_node("evaluate_state", evaluate_state)
    burt_workflow.add_node("more_info_follow_up", more_info_follow_up)
    burt_workflow.add_node("interrupt_and_present", interrupt_and_present)
    burt_workflow.add_node("generate_report", generate_final_report)

    burt_workflow.set_entry_point("information_element_extraction")
    burt_workflow.add_edge("information_element_extraction", "clarity_check")
    burt_workflow.add_conditional_edges(
        "clarity_check",
        should_route_clarity,
        {
            "continue": "map_to_graph",
            "needs_clarification": "clarity_follow_up",
        }
    )
    burt_workflow.add_edge("clarity_follow_up", "interrupt_and_present")
    burt_workflow.add_edge("map_to_graph", "evaluate_state")
    burt_workflow.add_conditional_edges(
        "evaluate_state",
        should_continue,
        {
            "continue": "more_info_follow_up",
            "end": "generate_report",
        }
    )
    burt_workflow.add_edge("more_info_follow_up", "interrupt_and_present")
    burt_workflow.add_edge("interrupt_and_present", "information_element_extraction")
    burt_workflow.add_edge("generate_report", END)

    return burt_workflow.compile(checkpointer=checkpointer)
