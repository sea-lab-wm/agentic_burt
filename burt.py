from dotenv import load_dotenv
from database.db import SessionLocal
from database.database_utils import fetch_app_graph
from state import BugAgentState
from graph_utils import stringify_current_bug_info, llm_extract, llm_check_clarity, llm_map, format_extraction_update, find_unknown_or_ambiguous, llm_follow_up, generate_report
from config import MODEL_NAME
from observability import log_action, Entity, ActionName, ConversationLogger
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from pprint import pprint

#loading in environment variables
load_dotenv()

#stand up db session
session = SessionLocal()

APP_GRAPH = None
current_bug = -1

#Select Bug being repored and fetch corresponding app graph from db
while not APP_GRAPH:
    current_bug = int(input("Enter valid ID for Bug Being Reported:"))
    APP_GRAPH = fetch_app_graph(session=session, bug_id=current_bug)

description_level = input("Please enter the description level as [completeness level]_[precision level]:")

#Set up conversation logger
logger = ConversationLogger(filepath=f"logs/bug{current_bug}_{description_level}.log", conversation_id=0)

#Model and APP_GRAPH Instantiation
MODEL = ChatOpenAI(model = MODEL_NAME)

#Node: Information Element Extraction (Scaffold)
def information_element_extraction(state: BugAgentState, config: RunnableConfig) -> dict:
    # Outside a clarification cycle, extract from the latest user message only.
    # During a clarification cycle, extract from the tracked message window.
    if state.clarification_window_start_idx == 0:
        user_messages = [state.messages[-1].content]
    else:
        window_messages = state.messages[state.clarification_window_start_idx :]
        user_messages = [message.content for message in window_messages]

    extraction = llm_extract(user_messages, MODEL)

    return {"information_element_extraction": extraction}

#Node: Clarity Check (Scaffold)
def clarity_check(state: BugAgentState, config: RunnableConfig) -> dict:
    extracted_info = state.information_element_extraction
    clarity_check= llm_check_clarity(extracted_info, MODEL)
    return {
        "clarity_route": clarity_check.clarity_route,
        "clarity_issues": clarity_check.clarity_issues,
    }

#Conditional edge behavior after clarity_check
#Routes to map_to_graph when no clarity issues exist, otherwise routes to clarity_follow_up
def should_route_clarity(state: BugAgentState):
    return state.clarity_route

#Node: Clarity Follow Up (Scaffold)
def clarity_follow_up(state: BugAgentState, config: RunnableConfig) -> dict:
    return {}

#Node 1: Map Information to Graph + Update (LLM)
    # A: Format Information of BugAgentState necessary for model call
        #state
        #application execution model / graph
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
    #capture the current BugInfo collected in JSON format
    stringified_bug_info = stringify_current_bug_info(state)

    #fetch the current app execution model/graph for the extraction prompt
    app_graph = (config.get("configurable") or {}).get("app_graph")

    #fetch the most recent agent follow up question if applicable
    follow_up_question = state.generated_question if state.generated_question else ""

    #current user description (either response to follow up or initial description of buggy behavior)
    user_description = state.messages[-1].content

    result = llm_map(stringified_bug_info, app_graph, follow_up_question, user_description, MODEL)
    
    return format_extraction_update(state, result)

#Node 2: Evaluate Internal Bug Report State for Completeness
@log_action(logger=logger, entity=Entity.bot, action_name=ActionName.evaluate)
def evaluate_state(state : BugAgentState, config : RunnableConfig) -> dict:
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
def follow_up(state : BugAgentState, config : RunnableConfig) -> dict:
    #Complete set of currently collected bug information (I figure the LLM needs good status fields to inform how it will ask to clarify poor status fields)
    stringified_bug_info = stringify_current_bug_info(state)

    #Application Execution Model/Graph
    app_graph = (config.get("configurable") or {}).get("app_graph")

    #Reference to low_confidence and missing bug info fields to speed up reasoning
    formatted_unknown_and_low_confidence_info = str(state.unknown_and_low_confidence_info)

    follow_up_question = llm_follow_up(stringified_bug_info, app_graph, formatted_unknown_and_low_confidence_info, MODEL)

    return {"generated_question" : follow_up_question}

#Node 4: Interupt (Stops the Graph Cycle so we can display generated follow question(s) and retrive answer's written by user) 
#See Review and Edit State section of LangChain intterupt docs for guidance: https://docs.langchain.com/oss/python/langgraph/interrupts
@log_action(logger=logger, entity=Entity.user, action_name=ActionName.user_description)
def interrupt_and_present(state : BugAgentState, config : RunnableConfig) -> dict:
    user_response = interrupt({"Follow Up Question": state.generated_question})
    return {"messages" : HumanMessage(content=user_response)}

#Generate Final Bug Report
@log_action(logger=logger, entity=Entity.user, action_name=ActionName.generate_report)
def gen_report(bug_info, app_graph):
    return generate_report(bug_info, app_graph, MODEL)

#Graph Construction:

#Instantiating Graph Nodes:
burt_workflow = StateGraph(BugAgentState)
burt_workflow.add_node("information_element_extraction", information_element_extraction)
burt_workflow.add_node("clarity_check", clarity_check)
burt_workflow.add_node("clarity_follow_up", clarity_follow_up)
burt_workflow.add_node("map_to_graph", map_to_graph)
burt_workflow.add_node("evaluate_state", evaluate_state)
burt_workflow.add_node("follow_up", follow_up)
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
        "continue" : "follow_up",
        "end": END
    } 
)
burt_workflow.add_edge("follow_up","interrupt_and_present")
burt_workflow.add_edge("interrupt_and_present","information_element_extraction")

#Establish Check Pointer for Persistant Memory During Interrupt
checkpointer = MemorySaver()
graph = burt_workflow.compile(checkpointer=checkpointer)

#Initializing Graph State and Logger (Information that Agent and User Update throughout conversation) and Config (Information that is constant and needed throughout agent lifecycle):

#Specifying a thread-id is how we ensure persistant state even with interupt
config = {"configurable": {"app_graph": APP_GRAPH, "thread_id": "1"}}

#For now, provide the initial user bug description to the loop, in a later GUI enabled version we can request it as first user message
state = BugAgentState(messages=[HumanMessage(content="The Parent Categories of the current category should be displayed.")])

result = graph.invoke(state, config=config)

#Control Flow
while True:
    #End sate reached: agent did not interrupt to request user answer to follow up question
    #Agent believes it is done collecting bug info
    if "__interrupt__" not in result:
        #state = result
        break

    #Display latest graph state from the checkpointer before asking the next follow-up
    # snapshot = graph.get_state(config)
    # print("STATE BEFORE NEXT FOLLOW UP:\n")
    # pprint(snapshot.values, width=100)
    # print("\n")

    #Agent requests user follow up response: present generated follow up question to user and retrieve their response
    question = result["__interrupt__"]
    print(question)
    user_response = input("> ")

    # Resume run; this returns updated state
    result = graph.invoke(Command(resume=user_response), config=config)

print("FINAL BUG REPORT:\n\n")
print(gen_report(result["BugInfo"], app_graph=APP_GRAPH))

#Write Logs to File
logger.write_log()
