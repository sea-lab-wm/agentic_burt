from state import BugAgentState, InfoSlots, SlotStatus, InformationElementExtraction
from llm_schema import ExtractionSchema, FollowUpSchema, ReportGenerationSchema, ClaritySchema
from langchain_core.prompts import ChatPromptTemplate
from typing import Any
import json


def file_to_string(filename):
    """
    Writes the contents of a file to a string. Used to capture the APP Graph so it can be injected into LLM prompts.
    
    :param filename: path to file
    """
    try:
        # Open the file in read mode ('r') using a 'with' statement
        with open(filename, 'r') as file:
            # Read all contents into a single string variable
            file_contents = file.read()
        return file_contents
    except FileNotFoundError:
        return f"Error: The file '{filename}' was not found."
    except Exception as e:
        return f"An error occurred: {e}"
    
def stringify_current_bug_info(state : BugAgentState):
    """
    Stringifies BugAgentState
    
    :param state: current BugAgentState object
    :type state: BugAgentState
    """
    bug_info = state.BugInfo
    
    return bug_info.model_dump_json()

def llm_extract(user_messages: list[str], model: Any) -> InformationElementExtraction:
    """
    Handles LLM query for information_element_extraction node.

    :param user_messages: ordered list of user descriptions from the active clarification window
    :type user_messages: list[str]
    :param model: active chat model
    :type model: Any
    :return: extracted natural language information elements
    :rtype: InformationElementExtraction
    """

    system_template = """You are an expert bug-report triage assistant.
    Your job is to extract natural-language information elements from user descriptions of a bug.

    You will receive one or more user descriptions. If there are multiple descriptions, merge them into one coherent extraction.

    Extraction Definitions:
    1. triggering_screen_reference: The application screen where performing the interaction causes the bug and/or the screen where the bug was observed.
    2. triggering_GUI_interactions: The user interaction(s) on the application that trigger the bug.
    3. buggy_behavior: The specific buggy behavior (the problem) reported in the bug.
    4. correct_behavior: The specific correct behavior that should happen instead of the buggy behavior.
    5. steps_to_reproduce: A contiguous sequence of application interactions starting from app launch and ending at the triggering screen.

    Strict Requirements:
    - Do not hallucinate or infer details not explicitly present in the user descriptions.
    - Only populate an element if user descriptions contain evidence for it.
    - Preserve user clarity: if wording is vague, keep it vague; do not rewrite into specific claims.
    - For each populated element, include evidence as exact short quotes from the user descriptions.
    - If an element is not present, leave it null.

    Output must follow the provided structured schema exactly.
    """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_template),
            ("human", "User descriptions:\n{user_messages}"),
        ]
    )

    formatted_messages = prompt.format_messages(
        user_messages="\n".join(f"- {message}" for message in user_messages),
    )

    structured = model.with_structured_output(InformationElementExtraction)
    extraction = structured.invoke(formatted_messages)
    return extraction

def llm_check_clarity(
    information_element_extraction: InformationElementExtraction, model: Any
) -> ClaritySchema:
    """
    Handles LLM query for clarity_check node.

    :param information_element_extraction: current extracted natural language information elements
    :type information_element_extraction: InformationElementExtraction
    :param model: active chat model
    :type model: Any
    :return: route decision and clarity issues
    :rtype: ClaritySchema
    """

    system_template = """You are an expert quality checker for bug-report information extraction.
    You will receive extracted information elements from user descriptions of bug report information.

    Task:
    1. Evaluate clarity of populated elements only.
    2. Detect ambiguous pronouns and confusing sentence structure.
    3. Return:
       - clarity_route = "continue" when the populated information is clear enough.
       - clarity_route = "needs_clarification" when any populated element is unclear.
    4. If clarity_route is "needs_clarification", populate clarity_issues with short issue strings.
    5. If clarity_route is "continue", return clarity_issues as an empty list.

    Rules:
    - Do not add new bug facts.
    - Keep issues concise and specific to fields.
    - If no fields are populated at all, route to "needs_clarification".
    """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_template),
            ("human", "{information_element_extraction}"),
        ]
    )

    formatted_messages = prompt.format_messages(
        information_element_extraction=information_element_extraction.model_dump_json(
            indent=2
        ),
    )

    structured = model.with_structured_output(ClaritySchema)
    clarity_result = structured.invoke(formatted_messages)
    return clarity_result

def llm_map(stringified_bug_info : str, app_graph : str, follow_up_question : str, user_description : str, model : Any) -> ExtractionSchema:
    """
    Handles LLM querry for extract and update node.
    
    :param stringified_bug_info: String representation of current agent state
    :type stringified_bug_info: str
    :param app_graph: String representation of current application execution model
    :type app_graph: str
    :param follow_up_question: Most recent follow up question generated by the follow_up node
    :type follow_up_question: str
    :param user_description: Initial user bug description or user response to generated follow up question
    :type user_description: str
    :return: ExtractionSchema object representing LLMs most recent mappings from user description to appliction execution model
    :rtype: Any
    """

    system_template ="""You are an expert bug reporter. 
    You will recieve a textual description written by an application user that contains information relating to a bug they experienced, a textual application graph that models the GUI hierarchy of the application the bug occured within and a set of information you already collected during your conversation with the user.
    The user's description is either a response to a follow up question you generated or an initial description of the bug the user experienced. 
    If the description is a respone to a follow up question, you will recieve the text of the folllow up question under === Follow Up Question === below, otherwise you will recieve a blank string to indicate the user description is an initial bug description. 

    Understanding the Application Graph:
    The Application Graph is divided into 2 sections, Transitions and States.
    Each line of the transitions section represents a GUI action or transition (button tap, swipe, etc.) that takes the user from source application screen to a target application screen.
    Each transition line follows this structure: [Unique Tranistion Hash Number]: (s: [Source Screen Hash Number],t: [Target Screen Hash Number]): [id=0, ex=0, sq=1, act=(0) [Action Type (ie. click, tap, swipe)], cp=[, ty= [Component Type (ie. button, tab, image)], idx=[component name], idnx=1, tx=[component text]], x=[Component lateral postion on screen]], y=[Component vertical position on screen], h=[Component height], w=[Component width], dsc=], txt=, exp=, tr=null] weight=[Numerical Weight Value Dictating How Often this Button Was Used When Traversing the Application] ds=TR sc=[Path to Screen Shot of Transition]] ex=0
    Each line of the states section represents a screen accessible in the GUI structure of the application.
    Each state line follows this structure: [Screen Hash Number], [Idenitfying Behavior of Screen]]..., TR, [Screen XML Meta Data]
    The application graph is included below.

    === Application Graph ===
    {app_graph}

    So far you have collected the information included below under 'Current Bug Information' during your conversation with the application user.

    === Current Bug Information ===
    {stringified_bug_info}

    === Follow Up Question ===
    {follow_up_question}

    Your task is to use the description provided by the user to compile the following information from the provided application graph. Please use the pre-existing bug information to inform any new information you draw from the application graph.

    === Desired Bug Information ===
    1. triggering_screen_reference: A **single** screen hash from the application graph of the application screen the bug occured on
    2. triggering_GUI_interactions: One to many transition hash numbers from the application graph representing the user interaction(s) that trigger(s) the bug
    3. buggy_behavior: A description of the application behavior that occured following the triggering_GUI_interactions, as described by the user
    4. correct_behavior: A description of the application behavior that should have occured following the triggering_GUI_interactions, as described by the user
    5. steps_to_reproduce: A list of transition hash numbers from the application graph that represent a continuous path of GUI actions, connecting the opening screen of the application to the triggering_screen_reference, where the bug was experienced. Please include the triggering_GUI_interactions in this list. Each entry in the list should be a **single** transition hash number.

    For each desired bug information please return your confidence in your decision ('unknown', 'ambiguous', 'inferred', 'confirmed') and a segment from the users description that informed your decsion. 
    Return your confidence and evidence for each step in the steps to reproduce. 
    Generate and return results according to the provided schema.
    If you cannot confidently identify part of the bug information above, leave the information unchanged or blank and mark the status as 'ambiguous' or 'unkown'.
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template),
        ("human", "{user_description}")
    
    ])

    messages = prompt.format_messages(
        app_graph = app_graph,
        stringified_bug_info = stringified_bug_info,
        follow_up_question = follow_up_question,
        user_description = user_description,
    )

    #create a wrapper around model calling that enforces that the model return information according to the ExtractionSchema above
    structured = model.with_structured_output(ExtractionSchema)

    extraction = structured.invoke(messages)

    return extraction

#This method will eventually check that the llm extracted information for triggering_screen_reference, triggering_GUI_interactions, and steps_to_reproduce are all valid hashes from the execution model
#def validate_llm_extract():

def format_extraction_update(state: BugAgentState, extraction: ExtractionSchema) -> dict:
    """
    Converts ExtractionSchema containing bug report information to format compatible with langraph node state update functionality (dict).
    Maintains current InfoSlots if LLM does not add them in its updated mapping.
    
    :param state: Current BugAgentState object
    :type state: BugAgentState
    :param extraction: Schema defining
    :type extraction: ExtractionSchema
    :return: Description
    :rtype: dict
    """
    current = state.BugInfo

    #In this current state, if the LLM does not add anything to the sate during its current extraction, the old state values are kept
    #Might need to change this later as the LLM should have the ability to reset a value to unknown if new information disuades it from its last selection for a specific field
    updated = InfoSlots(
        triggering_screen_reference=extraction.triggering_screen_reference or current.triggering_screen_reference,
        triggering_GUI_interactions=extraction.triggering_GUI_interactions or current.triggering_GUI_interactions,
        buggy_behavior=extraction.buggy_behavior or current.buggy_behavior,
        correct_behavior=extraction.correct_behavior or current.correct_behavior,
        steps_to_reproduce=extraction.steps_to_reproduce or current.steps_to_reproduce,
    )
    return {
        "BugInfo": updated,
        #"last_extraction_raw": extraction.model_dump_json(),
    }

def find_unknown_or_ambiguous(info: InfoSlots):
    """
    Scans through all bug info slots(buggy screen, expected behavior, etc.) and flags info slots with low confidence or unknown status
    
    :param info: InfoSlots from active BugAgentState object
    :type info: InfoSlots
    """
    flagged = set()

    for name, content in info:
        if name == "steps_to_reproduce" or name == "triggering_GUI_interactions":
            if not content:
                flagged.add(f"{name}")
                
            for i, step in enumerate(content):
                if step.status in {SlotStatus.unknown, SlotStatus.ambiguous}:
                    flagged.add(f"{name}[{i}]")
        else:
            if content.status in {SlotStatus.unknown, SlotStatus.ambiguous}:
                flagged.add(name)

    return flagged

def llm_follow_up(stringified_bug_info : str, app_graph : str, formatted_unknown_and_low_confidence_info : str, model : Any) -> FollowUpSchema:

    """
    Handles LLM query to generate follow up question based on unknown and low confidence InfoSlots in current agent state.
    
    :param stringified_bug_info: String representation of current agent state
    :type stringified_bug_info: str
    :param app_graph: String representation of current application execution model
    :type app_graph: str
    :param formatted_unknown_and_low_confidence_info: Stringified reference list of names of fields identified as low confidence or unknown
    :type formatted_unknown_and_low_confidence_info: str
    :return: A FollowUpSchema object containing a follow up question to be present to the user
    :rtype: Any
    """

    system_template ="""You are an expert bug report.
    You will recieve a textual application graph that models the GUI hierarchy of the application the bug occured within, a set of information you already collected during your conversation with the user and list referencing specific low confidence or unknown information that you want the user to clarify.

    Understanding the Application Graph:
    Each line of the application graph represents a GUI action or transition (button tap, swipe, etc.) that takes the user from source application screen to a target application screen.
    Each line of the application graph follows this structure: [Unique Tranistion Hash Number]: (s: [Source Screen Hash Number],t: [Target Screen Hash Number]): [id=0, ex=0, sq=1, act=(0) [Action Type (ie. click, tap, swipe)], cp=[, ty= [Component Type (ie. button, tab, image)], idx=[component name], idnx=1, tx=[component text]], x=[Component lateral postion on screen]], y=[Component vertical position on screen], h=[Component height], w=[Component width], dsc=], txt=, exp=, tr=null] weight=[Numerical Weight Value Dictating How Often this Button Was Used When Traversing the Application] ds=TR sc=[Path to Screen Shot of Transition]] ex=0
    The application graph is included below.

    === Application Graph ===
    {app_graph}

    So far you have collected the information included below under 'Current Bug Information' during your conversation with the application user.

    === Current Bug Information ===
    {stringified_bug_info}

    The section below outlines what each information category from the Current Bug Information contains:
    1. triggering_screen_reference: A **single** screen hash from the application graph of the application screen the bug occured on
    2. triggering_GUI_interactions: One to many transition hash numbers from the application graph representing the user interaction(s) that trigger(s) the bug
    3. buggy_behavior: A description of the application behavior that occured following the triggering_GUI_interactions, as described by the user
    4. correct_behavior: A description of the application behavior that should have occured following the triggering_GUI_interactions, as described by the user
    5. steps_to_reproduce: A list of transition hash numbers from the application graph that represent a continuous path of GUI actions, connecting the opening screen of the application to the triggering_screen_reference, where the bug was experienced. Please include the triggering_GUI_interactions in this list. Each entry in the list should be a **single** transition hash number.

    Here is a list of low confidence and missing bug information.
    If you see a list item of the form, "steps_to_reproduce[i], that is specifying that the ith step to reproduce is low_confidence or missing."
    {formatted_unknown_and_low_confidence_info}

    Your task is to generate a **single** follow up question, guided by 'inferred' or 'confirmed' status current bug information and the structure of the application the bug appeard on defined by the application graph, to prompt a user to provide clarification on **one** low confidence or missing bug information fields.
    Please prioritize unknown status information over ambiguos information.
    Please return your follow up question in the format specified in the FollowUpSchema.
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template)
    
    ])

    messages = prompt.format_messages(
        app_graph = app_graph,
        stringified_bug_info = stringified_bug_info,
        formatted_unknown_and_low_confidence_info = formatted_unknown_and_low_confidence_info,
    )

    structured = model.with_structured_output(FollowUpSchema)

    result = structured.invoke(messages)

    return result.follow_up_question

def process_bug_info(complete_bug_info : InfoSlots):
    """
    Extracts values from InfoSlots into a plain dict and returns a string dump.

    :param complete_state: Completed BugAgentState object
    :type complete_state: BugAgentState
    :return: Stringified dict of bug info values
    :rtype: str
    """
    bug_info_values = {
        "triggering_screen_reference": complete_bug_info.triggering_screen_reference.value,
        "triggering_GUI_interactions": [interaction.value for interaction in complete_bug_info.triggering_GUI_interactions],
        "buggy_behavior": complete_bug_info.buggy_behavior.value,
        "correct_behavior": complete_bug_info.correct_behavior.value,
        "steps_to_reproduce": [step.value for step in complete_bug_info.steps_to_reproduce],
    }

    return json.dumps(bug_info_values)

def generate_report(complete_bug_info : InfoSlots, app_graph : str, model : Any) -> str:
    """
    Generate High-Quality Textual Bug Report from Complete Bug InfoSlots
    """

    bug_info = process_bug_info(complete_bug_info)

    system_template = """
    # Task Summary
    You are an expert developer of Android applications. Given information collected for a **user-experienced bug** on an android application, your task is to generate a **high-quality structured bug report** with four sections: **Title**, **Observed Behavior (OB)**, **Expected Behavior (EB)**, and **Steps to Reproduce (S2Rs)**. 

    You will be given the following information about the **user-experienced bug** created based on a textual graph of the buggy applications user interface:
    1. triggering_screen_reference: A **single** screen hash from the application graph of the application screen the bug occured on
    2. triggering_GUI_interactions: One to many transition hash numbers from the application graph representing the user interaction(s) that trigger(s) the bug
    3. buggy_behavior: A description of the application behavior that occured following the triggering_GUI_interactions, as described by the user
    4. correct_behavior: A description of the application behavior that should have occured following the triggering_GUI_interactions, as described by the user
    5. steps_to_reproduce: A list of transition hash numbers from the application graph that represent a continuous path of GUI actions, connecting the opening screen of the application to the triggering_screen_reference, where the bug was experienced. Please include the triggering_GUI_interactions in this list. Each entry in the list should be a **single** transition hash number.

    === Understanding the Textual Graph of the Buggy Application =====
    The triggering_GUI_interactions and steps_to_reproduce hashes map to edges or tansitions in the textual graph, which appear in the following format: 
    [Unique Transition Hash Number]: (s: [Source Screen Hash Number],t: [Target Screen Hash Number]): [id=0, ex=0, sq=1, act=(0) [Action Type (ie. click, tap, swipe)], cp=[, ty= [Component Type (ie. button, tab, image)], idx=[component name], idnx=1, tx=[component text]], x=[Component lateral postion on screen]], y=[Component vertical position on screen], h=[Component height], w=[Component width], dsc=], txt=, exp=, tr=null] weight=[Numerical Weight Value Dictating How Often this Button Was Used When Traversing the Application] ds=TR sc=[Path to Screen Shot of Transition]] ex=0

    The triggering_screen_reference hash represents a node or state in the textual graph, which appear in the following format: [Screen Hash Number], [Identifying Behavior of Screen]]..., TR, [Screen XML Meta Data]

    You will be provided with the textual graph of the buggy application user interface below. 

    === Generation Guidelines ===
    buggy_behavior and expected_behavior are textual descriptions and can be used verbatim if desired.
    Please do NOT reference any hash numbers from the application graph in your generated bug report sections.

    ---

    # Inputs

    ##Bug Information
    {bug_info}

    ##Textual Application Graph
    {app_graph}

    ---

    # Instructions for Generating the four sections of the **high-quality structured bug report**

    1. **Title**
    - Write one concise sentence that summarizes the problem clearly.

    2. **Observed Behavior (OB)**
    - Use the identified **triggering_screen_reference**, **triggering_GUI_interactions**, and **buggy_behavior**.
    - Only use information from the provided inputs; do not hallucinate any `information element` if that is not available.
    - If the screen name is not explicitly found in the available inputs, generate a general name for the screen using the screen description.
    - Use this template to write the OB description: On [Triggering Screen Reference], if the user [Triggering GUI Interaction], the [Buggy Behavior].
    - Adapt the template if needed, but do not add unmentioned details.

    3. **Expected Behavior (EB)**
    - Use the provided **correct_behavior** field.
    - Use this template to write the EB description: [subject] should/should not [Correct Behavior/Incorrect Behavior].
    - Adapt the template if needed, but do not add unmentioned details.
    - Do not repeat information that is already mentioned in the OB.

    4. **Steps to Reproduce (S2R)**
    - Use the provided **steps_to_reproduce** field
    - Generate textual descriptions for every single step to reproduce provided in the bug information

    5. **Generation Requirements**
    - Do not hallucinate or introduce details not present in the input data.
    - Maintain language clarity, precision, and consistency across all sections.

    8. **Output Instructions**
    - Provide a structured response enforced by the given pydantic model. 

    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template)
    
    ])

    messages = prompt.format_messages(
        bug_info = bug_info,
        app_graph = app_graph,
    )

    structured = model.with_structured_output(ReportGenerationSchema)

    result = structured.invoke(messages)

    return result.model_dump()
    
