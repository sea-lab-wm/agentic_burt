import argparse
import csv
from dotenv import load_dotenv
from database.db import SessionLocal
from database.database_utils import fetch_app_graph_and_name
from state import BugAgentState
from graph_utils import llm_extract, llm_check_clarity, llm_clarity_follow_up, llm_map, format_extraction_update, find_unknown_or_ambiguous, llm_more_info_follow_up, generate_report
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
logger = ConversationLogger(filepath="logs/V2/session.log", conversation_id=0)

#Model instantiation with callback for token usage
usage_callback = ObservabilityTokenCallback(logger=logger)
MODEL = ChatOpenAI(model=config.MODEL_NAME, callbacks=[usage_callback])
DESCRIPTION_CSV_PATH = Path(config.DESCRIPTION_CSV_PATH)


def parse_args() -> argparse.Namespace:
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

    raise ValueError(
        f"Bug ID {current_bug} was not found in {DESCRIPTION_CSV_PATH}."
    )

def initialize_runtime(current_bug: int, description_level: str) -> tuple[str, str]:
    session = SessionLocal()
    try:
        app_graph, app_name = fetch_app_graph_and_name(session=session, bug_id=current_bug)
    finally:
        session.close()

    if not app_graph or not app_name:
        raise ValueError(f"No app graph/app name found for bug ID {current_bug}.")

    version = str(config.PROMPT_VERSION)
    logger.filepath = Path(f"logs/{version}/bug{current_bug}_{description_level}.log")
    logger.conversation_id = str(current_bug)
    return app_graph, app_name

#Node: Information Element Extraction
@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.information_element_extraction)
def information_element_extraction(state: BugAgentState, config: RunnableConfig) -> dict:
    print("extracting information elements...\n")
    app_name = (config.get("configurable") or {}).get("app_name")

    # Outside a clarification cycle, extract from the latest user message only.
    # During a clarification cycle, extract from the tracked message window.
    window_messages = state.messages[state.clarification_window_start_idx:]
    user_messages = [message.content for message in window_messages]

    is_follow_up_response = state.generated_question is not None and len(state.messages) > 1
    extraction_mode = "follow_up" if is_follow_up_response else "initial"
    follow_up_question = state.generated_question if is_follow_up_response else None

    extraction = llm_extract(
        user_messages=user_messages,
        model=MODEL,
        app_name=app_name,
        follow_up_question=follow_up_question,
        extraction_mode=extraction_mode,
    )

    return {
        "information_element_extraction": extraction
    }

#Node: Clarity Check
@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.clarity_check)
def clarity_check(state: BugAgentState, config: RunnableConfig) -> dict:
    print("checking clarity...\n")
    app_name = (config.get("configurable") or {}).get("app_name")
    extracted_info = state.information_element_extraction
    clarity_check= llm_check_clarity(extracted_info, MODEL, app_name)
    return {
        "clarity_route": clarity_check.clarity_route,
        "clarity_issues": clarity_check.clarity_issues,
    }

#Conditional edge behavior after clarity_check
#Routes to map_to_graph when no clarity issues exist, otherwise routes to clarity_follow_up
def should_route_clarity(state: BugAgentState):
    if state.clarification_rounds < 1:
        return state.clarity_route
    else:
        return "continue"

#Node: Clarity Follow Up
@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.clarity_follow_up)
def clarity_follow_up(state: BugAgentState, config: RunnableConfig) -> dict:
    print("following up on clarity issues...\n")
    app_name = (config.get("configurable") or {}).get("app_name")
    clarity_issues = state.clarity_issues
    information_elements = state.information_element_extraction
    follow_up_question = llm_clarity_follow_up(
        information_elements, clarity_issues, MODEL, app_name
    )
    return {
        "generated_question": follow_up_question,
        "clarification_rounds": (state.clarification_rounds + 1),
    }

#Node 1: Map Information to Graph + Update (LLM)
    # A: Format Information of BugAgentState necessary for model call
        #current agent state
        #application execution model / graph
        #labeled extracted information elements
        #user response
    # B: Submit a prompt to MODEl  the following and enfore that response is in JSON format:
        # System Prompt instructing the LLM of its job
        # Textual graph for current application structure 
        # Textual Snapshot of Current Agent State
        # Users most recent response
        # Few shot examples of how to extract info from the response
    # C: Parse the JSON formatted response from MODEL into dict for update to BugAgentState
    # D: Return update to BugAgentState
@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.extract_and_update)
def map_to_graph(state : BugAgentState, config : RunnableConfig):
    print("mapping collected information to graph...\n")
    #capture the current BugInfo collected in JSON format
    current_bug_info = state.BugInfo

    #fetch the current app execution model/graph for the extraction prompt
    app_graph = (config.get("configurable") or {}).get("app_graph")
    app_name = (config.get("configurable") or {}).get("app_name")

    #fetch the most recent extracted information elements 
    extracted_infomration_elements = state.information_element_extraction 

    result = llm_map(
        current_bug_info=current_bug_info,
        app_graph=app_graph,
        extracted_information_elements=extracted_infomration_elements,
        model=MODEL,
        app_name=app_name,
    )
    
    return format_extraction_update(state, result)

#Node 2: Evaluate Internal Bug Report State for Completeness
@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.evaluate)
def evaluate_state(state : BugAgentState, config : RunnableConfig) -> dict:
    print("evaluating collected information...\n")
    current_bug_info = state.BugInfo

    return {"unknown_and_low_confidence_info" : find_unknown_or_ambiguous(current_bug_info)}

#This function defines the behavior of the conditional edge after the evaluate_state node
#If the agent has collected complete bug information, this edge will direct the agent to move to report generation
#Otherise, the agent will proceed to asking more follow ups to clarify the unknown or ambiguous bug information
def should_continue(state : BugAgentState):    
    if state.unknown_and_low_confidence_info:
        return "continue"
    else:
        return "end"

#Node 3: Generate Follow Up Questions to Fill in Gaps in Bug Report State
    #A: Extract/Stringfy Low Confidence and Unknown bug info from the BugInfo slots based on references in missing_and_low_confidence_info
    #B: Compile and Ship prompt requesting that LLM choose field and ask follow up questions (Enforce Structured Output)
    #C: Capture generated follow up question and return partial update to 'generated_question' field of BugAgentState
@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.follow_up)
def more_info_follow_up(state : BugAgentState, config : RunnableConfig) -> dict:
    print("following up on missing information...\n")
    #Complete set of currently collected bug information (I figure the LLM needs good status fields to inform how it will ask to clarify poor status fields)
    current_bug_info = state.BugInfo

    #Application Execution Model/Graph
    app_graph = (config.get("configurable") or {}).get("app_graph")
    app_name = (config.get("configurable") or {}).get("app_name")

    #Reference to low_confidence and missing bug info fields to speed up reasoning
    formatted_unknown_and_low_confidence_info = str(state.unknown_and_low_confidence_info)

    follow_up_question = llm_more_info_follow_up(
        current_bug_info,
        app_graph,
        formatted_unknown_and_low_confidence_info,
        MODEL,
        app_name,
    )

    return {"generated_question" : follow_up_question}

#Node 4: Interupt (Stops the Graph Cycle so we can display generated follow question(s) and retrive answer's written by user) 
#See Review and Edit State section of LangChain intterupt docs for guidance: https://docs.langchain.com/oss/python/langgraph/interrupts
@log_action(logger=logger, entity=Entity.user, action_name=ActionName.user_description)
def interrupt_and_present(state : BugAgentState, config : RunnableConfig) -> dict:
    user_response = interrupt({"Follow Up Question": state.generated_question})
    return {"messages" : HumanMessage(content=user_response)}

#Generate Final Bug Report
@log_action(logger=logger, entity=Entity.user, action_name=ActionName.generate_report)
def gen_report(bug_info, app_graph, app_name):
    print("generating final bug report...\n")
    unresolved = find_unknown_or_ambiguous(bug_info)
    if unresolved:
        raise ValueError(
            f"Cannot generate report with unresolved bug info: {sorted(unresolved)}"
        )
    return generate_report(bug_info, app_graph, MODEL, app_name)

#Graph Construction:

#Instantiating Graph Nodes:
burt_workflow = StateGraph(BugAgentState)
burt_workflow.add_node("information_element_extraction", information_element_extraction)
burt_workflow.add_node("clarity_check", clarity_check)
burt_workflow.add_node("clarity_follow_up", clarity_follow_up)
burt_workflow.add_node("map_to_graph", map_to_graph)
burt_workflow.add_node("evaluate_state", evaluate_state)
burt_workflow.add_node("more_info_follow_up", more_info_follow_up)
burt_workflow.add_node("interrupt_and_present", interrupt_and_present)

#Establishing Graph Edges and Agent Behavior:
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

#Establish Check Pointer for Persistant Memory During Interrupt
checkpointer = MemorySaver()
graph = burt_workflow.compile(checkpointer=checkpointer)

def main() -> None:
    args = parse_args()
    initial_message = load_initial_message(
        current_bug=args.bug_id,
        description_level=args.description_level,
    )
    app_graph, app_name = initialize_runtime(
        current_bug=args.bug_id,
        description_level=args.description_level,
    )

    #Specifying a thread-id is how we ensure persistant state even with interupt
    config = {"configurable": {"app_graph": app_graph, "app_name": app_name, "thread_id": "1"}}
    state = BugAgentState(messages=[HumanMessage(content=initial_message)])

    logger.start_conversation()
    result = graph.invoke(state, config=config)

    #Control Flow
    while True:
        #End sate reached: agent did not interrupt to request user answer to follow up question
        #Agent believes it is done collecting bug info
        if "__interrupt__" not in result:
            break

        #Display latest graph state from the checkpointer before asking the next follow-up
        snapshot = graph.get_state(config)
        print("STATE BEFORE NEXT FOLLOW UP:\n")
        pprint(snapshot.values, width=100)
        print("\n\n")

        #Agent requests user follow up response: present generated follow up question to user and retrieve their response
        question = result["__interrupt__"]
        print(question)
        user_response = input("> ")

        # Resume run; this returns updated state
        result = graph.invoke(Command(resume=user_response), config=config)

    print("FINAL BUG REPORT:\n\n")
    final_report = gen_report(result["BugInfo"], app_graph=app_graph, app_name=app_name)
    print(final_report["full_report"])
    logger.finish_conversation()
    logger.write_log()


if __name__ == "__main__":
    main()
