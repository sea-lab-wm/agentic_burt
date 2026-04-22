import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import Literal
import redis
from state import ActiveFollowUp, BugAgentState, FollowUpKind
from agent_utils import llm_extract, llm_check_clarity, llm_clarity_follow_up, llm_map, format_extraction_update, find_unknown_or_ambiguous, format_unknown_or_ambiguous_references, llm_more_info_follow_up, generate_report
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
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from pprint import pprint
from pathlib import Path

#loading in environment variables
load_dotenv()

DESCRIPTION_CSV_PATH = Path(config.DESCRIPTION_CSV_PATH)

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
    bug_id: int,
    description_level: str,
    sink_mode: Literal["local", "redis_then_file"] = "local",
    redis_client: redis.Redis | None = None,
) -> BurtRuntimeContext:
    """Create the logger, callback, and model instances for one conversation request."""

    version = str(config.PROMPT_VERSION)
    log_path = Path("logs") / version / f"session_{session_id}_bug{bug_id}_{description_level}.log"

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

def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for one BURT runtime invocation."""
    parser = argparse.ArgumentParser(description="Run the BURT bug-report workflow.")
    parser.add_argument(
        "--bug-id",
        type=int,
        required=True,
        help="Bug ID used to fetch the app graph and app name.",
    )
    parser.add_argument(
        "--description-level",
        required=True,
        help="Description level in the format [completeness level]_[precision level].",
    )
    
    return parser.parse_args()

def normalize_description_level(description_level: str) -> str:
    """Normalize and validate a description-level string such as ``LC_LP``."""
    normalized = description_level.strip().upper().replace("-", "_")
    try:
        completeness_level, precision_level = normalized.split("_", maxsplit=1)
    except ValueError as exc:
        raise ValueError(
            "Description level must use the format [L|M|H]C_[L|M|H]P, for example LC_MP."
        ) from exc

    if len(completeness_level) != 2 or completeness_level[1] != "C":
        raise ValueError(
            "Completeness level must be one of LC, MC, HC."
        )
    if len(precision_level) != 2 or precision_level[1] != "P":
        raise ValueError(
            "Precision level must be one of LP, MP, HP."
        )

    if completeness_level[0] not in {"L", "M", "H"} or precision_level[0] not in {"L", "M", "H"}:
        raise ValueError(
            "Description level must use only L, M, or H prefixes."
        )

    return f"{completeness_level}_{precision_level}"

def load_initial_message(current_bug: int, description_level: str) -> str:
    """Load the initial user description for one bug and description level."""
    normalized_level = normalize_description_level(description_level)
    description_column = f"{normalized_level} Desc"

    with DESCRIPTION_CSV_PATH.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            if row.get("bug_id") != str(current_bug):
                continue

            initial_message = (row.get(description_column) or "").strip()
            if not initial_message:
                raise ValueError(
                    f"No initial message found for bug ID {current_bug} and description level {normalized_level}."
                )
            return initial_message

    raise ValueError(f"Bug ID {current_bug} was not found in {DESCRIPTION_CSV_PATH}.")

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

    return {
        "active_follow_up": ActiveFollowUp(
            kind=FollowUpKind.more_info,
            question=follow_up.follow_up_question,
            target_info_elements=follow_up.clarification_target_info_elements,
        )
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

def main() -> None:
    """Run one complete BURT CLI session from input load through log write."""

    #load graph data for specific description
    args = parse_args()
    initial_message = load_initial_message(
        current_bug=args.bug_id,
        description_level=args.description_level,
    )
    transitions, app_name, screen_descriptions = load_bug_graph_context(
        current_bug=args.bug_id
    )

    #session id placeholder to ensure other functionality works, might want to change this to make a unique session id or do dev on containers
    runtime_context = create_runtime_context(
        session_id="local",
        bug_id=args.bug_id,
        description_level=args.description_level,
    )

    #this guarantees that every CLI run writes a new log, instead of appending onto old logs of the same name
    runtime_context.logger.filepath.unlink(missing_ok=True)

    #configure initial state of graph
    graph = build_burt_graph(MemorySaver())
    config = {
        "configurable": {
            "transitions": transitions,
            "app_name": app_name,
            "screen_descriptions": screen_descriptions,
            "thread_id": "1",
            "runtime_context": runtime_context,
        }
    }
    initial_state_update = ingest_user_description(
        initial_message,
        runtime_context=runtime_context,
    )
    state = BugAgentState(messages=[initial_state_update["messages"]])

    result = graph.invoke(state, config=config)
    _flush_active_turn(runtime_context)

    while True:
        #The graph interrupts its execution flow to ask user questions
        #Here if an interupt tag is detected in the output of the graph, we display the most recent generate question for the user to answer through command line
        if "__interrupt__" not in result:
            break

        snapshot = graph.get_state(config)
        print("STATE BEFORE NEXT FOLLOW UP:\n")
        pprint(snapshot.values, width=100)
        print("\n\n")

        question = result["__interrupt__"]
        print(question)
        user_response = input("> ")

        result = graph.invoke(Command(resume=user_response), config=config)
        _flush_active_turn(runtime_context)

    print("FINAL BUG REPORT:\n\n")
    final_report = result["full_report"]
    print(final_report)
    runtime_context.sink.finalize_session(
        session_id=runtime_context.session_id,
        final_report=final_report,
    )

if __name__ == "__main__":
    main()
