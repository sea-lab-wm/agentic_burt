import argparse
import csv
from dotenv import load_dotenv
from database.db import SessionLocal
from database.database_utils import fetch_graph_data
from state import ActiveFollowUp, BugAgentState, FollowUpKind
from graph_utils import llm_extract, llm_check_clarity, llm_clarity_follow_up, llm_map, format_extraction_update, find_unknown_or_ambiguous, format_unknown_or_ambiguous_references, llm_more_info_follow_up, generate_report
import config
from observability import (
    ActionName,
    ConversationLogger,
    Entity,
    ObservabilityTokenCallback,
    log_action,
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

#Set up conversation logger
logger = ConversationLogger(filepath="logs/placeholder,log", conversation_id=0)

#Model instantiation with callback for token usage
usage_callback = ObservabilityTokenCallback(logger=logger)
MODEL = ChatOpenAI(model=config.MODEL_NAME, callbacks=[usage_callback])
DESCRIPTION_CSV_PATH = Path(config.DESCRIPTION_CSV_PATH)


@log_action(logger=logger, entity=Entity.user, action_name=ActionName.user_description)
def ingest_user_description(user_text: str) -> dict:
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

def initialize_runtime(current_bug: int, description_level: str) -> tuple[str, str, str]:
    """Fetch runtime graph context and configure the versioned log path."""
    session = SessionLocal()
    try:
        app_graph, app_name, screen_descriptions = fetch_graph_data(session=session, bug_id=current_bug)
    finally:
        session.close()

    if not app_graph or not app_name:
        raise ValueError(f"No app graph/app name found for bug ID {current_bug}.")

    version = str(config.PROMPT_VERSION)
    logger.filepath = Path(f"logs/{version}/bug{current_bug}_{description_level}.log")
    logger.conversation_id = str(current_bug)
    return app_graph, app_name, screen_descriptions

@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.information_element_extraction)
def information_element_extraction(state: BugAgentState, config: RunnableConfig) -> dict:
    """Extract natural-language information elements from the active user window."""
    print("extracting information elements...\n")
    app_name = (config.get("configurable") or {}).get("app_name")

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
        model=MODEL,
        app_name=app_name,
        follow_up_question=follow_up_question,
        extraction_mode=extraction_mode,
        target_info_elements=target_info_elements,
    )

    return {
        "information_element_extraction": extraction
    }

@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.clarity_check)
def clarity_check(state: BugAgentState, config: RunnableConfig) -> dict:
    """Check whether the extracted information elements are clear enough to map."""
    print("checking clarity...\n")
    app_name = (config.get("configurable") or {}).get("app_name")
    extracted_info = state.information_element_extraction
    clarity_result = llm_check_clarity(extracted_info, MODEL, app_name)
    return {
        "clarity_route": clarity_result.clarity_route,
        "clarity_issues": clarity_result.clarity_issues,
    }

def should_route_clarity(state: BugAgentState):
    """Route one post-clarity step, allowing at most one clarification follow up if needed."""
    if state.clarification_rounds < 1:
        return state.clarity_route
    return "continue"

@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.clarity_follow_up)
def clarity_follow_up(state: BugAgentState, config: RunnableConfig) -> dict:
    """Generate a follow-up question that resolves clarity issues."""
    print("following up on clarity issues...\n")
    app_name = (config.get("configurable") or {}).get("app_name")
    clarity_issues = state.clarity_issues
    information_elements = state.information_element_extraction
    follow_up = llm_clarity_follow_up(
        information_elements, clarity_issues, MODEL, app_name
    )
    return {
        "active_follow_up": ActiveFollowUp(
            kind=FollowUpKind.clarity,
            question=follow_up.follow_up_question,
            target_info_elements=[],
        ),
        "clarification_rounds": (state.clarification_rounds + 1),
    }

@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.extract_and_update)
def map_to_graph(state : BugAgentState, config : RunnableConfig) -> dict:
    """Ground extracted information elements into the structured bug mapping."""
    print("mapping collected information to graph...\n")
    current_bug_info = state.BugInfo

    app_graph = (config.get("configurable") or {}).get("app_graph")
    app_name = (config.get("configurable") or {}).get("app_name")
    screen_name_and_description_list = (config.get("configurable") or {}).get("screen_descriptions")

    extracted_information_elements = state.information_element_extraction

    result = llm_map(
        current_bug_info=current_bug_info,
        app_graph=app_graph,
        screen_name_and_description_list=screen_name_and_description_list,
        extracted_information_elements=extracted_information_elements,
        model=MODEL,
        app_name=app_name,
    )
    
    return format_extraction_update(state, result)

@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.evaluate)
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

@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.follow_up)
def more_info_follow_up(state : BugAgentState, config : RunnableConfig) -> dict:
    """Generate a follow-up question for unresolved bug-info fields."""
    print("following up on missing information...\n")
    current_bug_info = state.BugInfo

    app_graph = (config.get("configurable") or {}).get("app_graph")
    app_name = (config.get("configurable") or {}).get("app_name")
    screen_name_and_description_list = (config.get("configurable") or {}).get("screen_descriptions")

    formatted_unknown_and_low_confidence_info = format_unknown_or_ambiguous_references(
        current_bug_info,
        state.unknown_and_low_confidence_info,
    )

    follow_up = llm_more_info_follow_up(
        current_bug_info,
        app_graph,
        screen_name_and_description_list,
        formatted_unknown_and_low_confidence_info,
        MODEL,
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
    return ingest_user_description(user_response)

@log_action(logger=logger, entity=Entity.user, action_name=ActionName.generate_report)
def gen_report(bug_info, app_graph, app_name) -> dict:
    """Generate the final report after confirming all bug-info slots are resolved."""
    print("generating final bug report...\n")
    unresolved = find_unknown_or_ambiguous(bug_info)
    if unresolved:
        raise ValueError(
            f"Cannot generate report with unresolved bug info: {sorted(unresolved)}"
        )
    return generate_report(bug_info, app_graph, MODEL, app_name)

burt_workflow = StateGraph(BugAgentState)
burt_workflow.add_node("information_element_extraction", information_element_extraction)
burt_workflow.add_node("clarity_check", clarity_check)
burt_workflow.add_node("clarity_follow_up", clarity_follow_up)
burt_workflow.add_node("map_to_graph", map_to_graph)
burt_workflow.add_node("evaluate_state", evaluate_state)
burt_workflow.add_node("more_info_follow_up", more_info_follow_up)
burt_workflow.add_node("interrupt_and_present", interrupt_and_present)

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
        "continue" : "more_info_follow_up",
        "end": END
    } 
)
burt_workflow.add_edge("more_info_follow_up","interrupt_and_present")
burt_workflow.add_edge("interrupt_and_present","information_element_extraction")

checkpointer = MemorySaver()
graph = burt_workflow.compile(checkpointer=checkpointer)

def main() -> None:
    """Run one complete BURT CLI session from input load through log write."""

    #load graph data for specific description
    args = parse_args()
    initial_message = load_initial_message(
        current_bug=args.bug_id,
        description_level=args.description_level,
    )
    app_graph, app_name, screen_descriptions = initialize_runtime(
        current_bug=args.bug_id,
        description_level=args.description_level,
    )

    #configure initial state of graph
    config = {"configurable": {"app_graph": app_graph, "app_name": app_name, "screen_descriptions": screen_descriptions, "thread_id": "1"}}
    initial_state_update = ingest_user_description(initial_message)
    state = BugAgentState(messages=[initial_state_update["messages"]])

    logger.start_conversation()
    result = graph.invoke(state, config=config)

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

    print("FINAL BUG REPORT:\n\n")
    final_report = gen_report(result["BugInfo"], app_graph=app_graph, app_name=app_name)
    print(final_report["full_report"])
    logger.finish_conversation()
    logger.write_log()


if __name__ == "__main__":
    main()
