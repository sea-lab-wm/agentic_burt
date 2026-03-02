from state import BugAgentState, InfoSlots, SlotStatus, InformationElementExtraction
from llm_schema import ExtractionSchema, FollowUpSchema, ReportGenerationSchema, ClaritySchema, ObservedExpectedToInfoElements
from langchain_core.prompts import ChatPromptTemplate
from typing import Any, Literal
import json


def llm_extract(
    user_messages: list[str],
    model: Any,
    app_name: str,
    follow_up_question: str | None = None,
    extraction_mode: Literal["initial", "follow_up"] = "initial",
) -> InformationElementExtraction:
    """
    Handles LLM query for information_element_extraction node.

    :param user_messages: ordered list of user descriptions from the active clarification window
    :type user_messages: list[str]
    :param model: active chat model
    :type model: Any
    :param app_name: application name for bug context
    :type app_name: str
    :param follow_up_question: last agent follow-up question, when extracting from a follow-up response
    :type follow_up_question: str | None
    :param extraction_mode: whether input text is an initial description or a follow-up response
    :type extraction_mode: Literal["initial", "follow_up"]
    :return: extracted natural language information elements
    :rtype: InformationElementExtraction
    """

    system_template = """You are an expert bug-report triage assistant for Android Apps. The user you are interacting with is reporting a bug on the {app_name} app.
    Your job is to extract natural-language information elements from user descriptions of a bug.

    You will receive one or more user descriptions, either intial user descriptions of a bug or a responses to follow up questions looking to clarify or gain more information into the details of the bug the user provided.
    You can identify which you have recieved based on the extraction mode passed in the user message. 
    If there are multiple descriptions, merge them into one coherent extraction.

    Extraction Definitions:
    1. triggering_screen_reference: The application screen where performing the interaction causes the bug and/or the screen where the bug was observed.
    2. triggering_GUI_interactions: The user interaction(s) on the application that trigger the bug.
    3. buggy_behavior: The specific buggy behavior (the problem) reported in the bug.
    4. correct_behavior: The specific correct behavior that should happen instead of the buggy behavior.
    5. steps_to_reproduce: A contiguous sequence of application interactions starting from app launch and ending at the triggering screen.

    Pronoun Resolution Rules:
    - Never assume a default referent for pronouns like "it", "this", "that", "they", "there".
    - Specifically, do NOT assume "it" means the whole app.
    - A pronoun is resolved only if its referent is explicitly identified in some provided user text or explicitly identified by a provided follow_up_question in follow_up mode.
    - If unresolved, keep the user wording verbatim and do not rewrite it into a specific app/screen/component claim.

    Strict Requirements:
    - Do not hallucinate or infer details not explicitly present in the user descriptions.
    - Only populate an element if user descriptions contain evidence for it.
    - Preserve user clarity: if wording is vague, keep it vague; do not rewrite into specific claims.
    - For each populated element, include evidence as exact short quotes from the user descriptions.
    - If an element is not present, leave it null.
    - If extraction_mode is "follow_up", use follow_up_question only to resolve references in the user's answer
      (for example, pronouns like "it" or "that screen"). Do NOT add facts not stated by the user.

    Output must follow the provided structured schema exactly.
    """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_template),
            (
                "human",
                "Extraction mode: {extraction_mode}\n"
                "Follow-up question (only relevant in follow_up mode):\n{follow_up_question}\n\n"
                "User descriptions:\n{user_messages}",
            ),
        ]
    )

    formatted_messages = prompt.format_messages(
        app_name=app_name,
        extraction_mode=extraction_mode,
        follow_up_question=follow_up_question or "N/A",
        user_messages="\n".join(f"- {message}" for message in user_messages),
    )

    structured = model.with_structured_output(InformationElementExtraction)
    extraction = structured.invoke(formatted_messages)
    print(f"Information Element Extraction: {extraction}\n")
    return extraction

def llm_check_clarity(
    information_element_extraction: InformationElementExtraction, model: Any, app_name: str
) -> ClaritySchema:
    """
    Handles LLM query for clarity_check node.

    :param information_element_extraction: current extracted natural language information elements
    :type information_element_extraction: InformationElementExtraction
    :param model: active chat model
    :type model: Any
    :param app_name: application name for bug context
    :type app_name: str
    :return: route decision and clarity issues
    :rtype: ClaritySchema
    """

    system_template = """You are an expert quality checker for bug-report information extraction.
    You will receive extracted key information elements from user descriptions of bug report information.

    Task:
    1. Evaluate clarity of populated elements only:
        - A populated element is clear only if it is referentially resolved.
        - Statements like "it restarted", "it broke", "it didn't work" are unclear unless other information elements provided clarify what it is.
    2. If any populated element is uncler, set clarity_route="needs_clarification", otherwise set clarity_route to "continue".
    3. If clarity_route is "needs_clarification", populate clarity_issues with short issue strings, otherwise return clarity_issues as an empty list.

    Return based on the given schema:
        1. clarity_route = "continue" when the populated information is clear enough.
        2. clarity_route = "needs_clarification" when any populated element is unclear.

    Rules:
    - Do not add new bug facts.
    - Do not worry about missing environment or application information in the information elements. 
    - Keep issues concise and specific to fields.
    - If there are no information elements provided, route to "needs_clarification".
    """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_template),
            ("human", "{information_element_extraction}"),
        ]
    )

    formatted_messages = prompt.format_messages(
        app_name=app_name,
        information_element_extraction=remove_empty_info_elements(information_element_extraction)
    )

    structured = model.with_structured_output(ClaritySchema)
    clarity_result = structured.invoke(formatted_messages)
    return clarity_result

def remove_empty_info_elements(info_elements : InformationElementExtraction) -> str:
    non_empty_sections = []

    for field_name, element in info_elements:
        if element is None:
            continue

        title = field_name.replace("_", " ").title()
        section_lines = [f"{title}:", f"- value: {element.value}"]

        if element.evidence:
            section_lines.append("- evidence:")
            section_lines.extend([f"  - {quote}" for quote in element.evidence])

        non_empty_sections.append("\n".join(section_lines))

    return "\n\n".join(non_empty_sections)

def llm_clarity_follow_up(
    information_element_extraction: InformationElementExtraction,
    clarity_issues: list[str],
    model: Any,
    app_name: str,
) -> str:
    """
    Handles LLM query to generate clarity-focused follow-up question(s).

    :param information_element_extraction: extracted natural language information elements
    :type information_element_extraction: InformationElementExtraction
    :param clarity_issues: list of clarity issues identified by clarity_check
    :type clarity_issues: list[str]
    :param model: active chat model
    :type model: Any
    :param app_name: application name for bug context
    :type app_name: str
    :return: follow-up question(s) to resolve clarity issues
    :rtype: str
    """

    system_template = """You are an expert bug triage assistant for Android Apps. You are currently working with the app {app_name}.
    You will receive extracted bug information elements and a list of clarity issues.

    Your task is to generate a single follow-up question, or a concise set of follow-up questions, to resolve the listed clarity issues.

    Requirements:
    - Focus only on resolving the listed clarity issues.
    - Do not ask questions to revieve more information about information elements you do not have.
    - Prioritize ambiguous pronouns and confusing sentence structure.
    - Keep question(s) concise and easy for a user to answer.
    - Return output following the FollowUpSchema.
    """

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_template),
            (
                "human",
                "=== Information Elements ===\n{information_element_extraction}\n\n=== Clarity Issues ===\n{clarity_issues}",
            ),
        ]
    )

    messages = prompt.format_messages(
        app_name=app_name,
        information_element_extraction=remove_empty_info_elements(information_element_extraction),
        clarity_issues="\n".join(f"- {issue}" for issue in clarity_issues),
    )

    structured = model.with_structured_output(FollowUpSchema)
    result = structured.invoke(messages)
    return result.follow_up_question

def llm_map(
    current_bug_info: InfoSlots,
    app_graph: str,
    extracted_information_elements: InformationElementExtraction,
    model: Any,
    app_name: str,
) -> ExtractionSchema:
    """
    Handles LLM query for the map_to_graph node.

    Uses extracted natural-language information elements and the existing mapped bug
    state to produce a structured mapping update grounded in the application graph.

    :param current_bug_info: Current grounded bug information state
    :type current_bug_info: InfoSlots
    :param app_graph: String representation of current application execution model
    :type app_graph: str
    :param extracted_information_elements: Labeled natural-language information elements
    :type extracted_information_elements: InformationElementExtraction
    :param model: Active chat model used for structured mapping
    :type model: Any
    :param app_name: application name for bug context
    :type app_name: str
    :return: Structured mapping update for bug information slots
    :rtype: ExtractionSchema
    """

    system_template ="""You are an expert bug reporter for android apps. You are currently reporting a bug on {app_name}. 
    You will recieve the following information: 
        1. A textual graph that models the GUI hierarchy of the application the bug occured within. You can learn how to understand the graph using the UNDERSTANDING THE APPLICATION GRAPH section below.
        2. A mapping that represents previously collected information from a conversation with the bug experiencing user mapped to states and edges on the application graph. You can learn how to understand the structure of the mapping below in the UNDERSTANDING MAPPING section below.
        3. A set of key bug report information elements extracted from a user description of a bug they experienced. Each element is labeled. You can learn more about the labels and how to undersand given information elements in the UNDERSTANDING INFORMATION ELEMENTS section below. 
        
    === UNDERSTANDING THE APPLICATION GRAPH =====
    The Application Graph is divided into 2 sections, Transitions and States.
    Each line of the transitions section represents a GUI action or transition (button tap, swipe, etc.) that takes the user from source application screen to a target application screen.
    Each transition line follows this structure: [Unique Tranistion Hash Number]: (s: [Source Screen Hash Number],t: [Target Screen Hash Number]): [id=0, ex=0, sq=1, act=(0) [Action Type (ie. click, tap, swipe)], cp=[, ty= [Component Type (ie. button, tab, image)], idx=[component name], idnx=1, tx=[component text]], x=[Component lateral postion on screen]], y=[Component vertical position on screen], h=[Component height], w=[Component width], dsc=], txt=, exp=, tr=null] weight=[Numerical Weight Value Dictating How Often this Button Was Used When Traversing the Application] ds=TR sc=[Path to Screen Shot of Transition]] ex=0
    Each line of the states section represents a screen accessible in the GUI structure of the application.
    Each state line follows this structure: [Screen Hash Number], [Idenitfying Behavior of Screen]]..., TR, [Screen XML Meta Data]

    === UNDERSTANDING MAPPING ===
    The mapping has 5 sections:
    1. triggering_screen_reference: A **single** screen hash from the application graph of the application screen the bug occured on
    2. triggering_GUI_interactions: One to many transition hash numbers from the application graph representing the user interaction(s) that trigger(s) the bug
    3. buggy_behavior: A description of the application behavior that occured following the triggering_GUI_interactions, as described by the user
    4. correct_behavior: A description of the application behavior that should have occured following the triggering_GUI_interactions, as described by the user
    5. steps_to_reproduce: A list of transition hash numbers from the application graph that represent a continuous path of GUI actions, connecting the opening screen of the application to the triggering_screen_reference, where the bug was experienced. Please include the triggering_GUI_interactions in this list. Each entry in the list should be a **single** transition hash number.
    Each section corresponds to an information element you might recieve. 
    Each entry in each section maps a part (triggering_GUI_interactions, steps_to_reproduce ) or all (triggering_screen_reference, buggy_behavior, correct_behavior) of the section to the graph. 
    Each entry comes with evidence, quotes from the information elements that informed the mapping, and a status, the confidence of the mapping, either ('unknown', 'ambiguous', 'inferred', 'confirmed'):
    'Confirmed': User evidence directly supports the mapped value (or near-paraphrase). No meaningful competing mapping.
    'Inferred': Mapped value is not directly stated, but is the single and most plausible conclusion from user evidence and context.
    'Ambiguous': User evidence is present but insufficiently specific; two or more plausible mappings remain. One tentative mapping has been chosen. For buggy behavior and correct behavior ambiguity refers to multiple plausible interpretations of described app behavior. For all other mappings, ambiguity refers to multiple plaussible state(screen)/transition(GUI action) hashes.
    'Unknown': No user evidence yet for this element.
    
    
    'Unknown' status indicates that the user has not provided that information element yet. 

    === UNDERSTANDING INFORMATION ELEMENTS ===
    There are 5 possible information elements you can recieve:
    1. triggering_screen_reference: The application screen where performing the interaction causes the bug and/or the screen where the bug was observed.
    2. triggering_GUI_interactions: The user interaction(s) on the application that trigger the bug.
    3. buggy_behavior: The specific buggy behavior (the problem) reported in the bug.
    4. correct_behavior: The specific correct behavior that should happen instead of the buggy behavior.
    5. steps_to_reproduce: A contiguous sequence of application interactions starting from app launch and ending at the triggering screen.
    You may recieve 1-5 descripitions of these information elements at any time. 

    Your task is to use the information elements provided to update the given mapping based on the provided application graph, this mapping will be used later to generate a high-quality, application structure accurate bug report. 
    Please use the pre-existing high-status bug information ('confirmed' or 'inferred') in the given mapping to inform any new information you draw from the application graph in your updates.
    Return the status and evidence for each update you make to the mapping, make sure you include status and evidence for each entry you update and leave status and evidence unchanged for entries in mapping you do not update. 
    If the information elements provided are not sufficient to update a certain part of the existing mapping, DO NOT stretch them or manipulate them to update 'unknown' or 'ambiguous' entries in the mapping.
    You may leave the mapping unchanged, leave sections empty or leave entries as ambiguous if you feel you do not have enough information to properly update thier mappings to high-status.
    Generate and return results according to the provided schema.
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template),
        (
            "human",
            "=== Application GUI Graph ===\n{app_graph}\n\n=== Previously Collected Information Mapping ===\n{previously_collected_information}\n\n=== Information Elements ===\n{extracted_information_elements}\n\n"
        )
    ])

    messages = prompt.format_messages(
        app_name=app_name,
        app_graph = app_graph,
        previously_collected_information = current_bug_info.model_dump_json(),
        extracted_information_elements=remove_empty_info_elements(extracted_information_elements)
        
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

def llm_more_info_follow_up(
    current_bug_info: InfoSlots,
    app_graph: str,
    formatted_unknown_and_low_confidence_info: str,
    model: Any,
    app_name: str,
) -> FollowUpSchema:

    """
    Handles LLM query to generate follow up question based on unknown and ambiguous InfoSlots in current agent state.
    
    :param stringified_bug_info: String representation of current agent state
    :type stringified_bug_info: str
    :param app_graph: String representation of current application execution model
    :type app_graph: str
    :param formatted_unknown_and_low_confidence_info: Stringified reference list of names of fields identified as ambiguous or unknown
    :type formatted_unknown_and_low_confidence_info: str
    :param app_name: application name for bug context
    :type app_name: str
    :return: A FollowUpSchema object containing a follow up question to be present to the user
    :rtype: Any
    """

    system_template ="""You are an expert bug reporter for Android apps. You are currently reporting on the app {app_name}.
    You will recieve the following information:
        1. A textual graph that models the GUI hierarchy of the application the bug occured within. You can understand the graph using the UNDERSTANDING THE APPLICATION GRAPH section below.
        2. A mapping that represents previously collected information from a conversation with the bug experiencing user mapped to states and edges on the application graph. You can understand the structure of the mapping in the UNDERSTANDING MAPPING section below.
        3. A list referencing specific ambiguous or unknown entries in the provided mapping that you need the user to further define. You can understand the structure of the reference list in the UNDERSTANDING AMBIGUOUS AND UNKNOWN REFERENCE LIST section below. 

     === UNDERSTANDING THE APPLICATION GRAPH =====
    The Application Graph is divided into 2 sections, Transitions and States.
    Each line of the transitions section represents a GUI action or transition (button tap, swipe, etc.) that takes the user from source application screen to a target application screen.
    Each transition line follows this structure: [Unique Tranistion Hash Number]: (s: [Source Screen Hash Number],t: [Target Screen Hash Number]): [id=0, ex=0, sq=1, act=(0) [Action Type (ie. click, tap, swipe)], cp=[, ty= [Component Type (ie. button, tab, image)], idx=[component name], idnx=1, tx=[component text]], x=[Component lateral postion on screen]], y=[Component vertical position on screen], h=[Component height], w=[Component width], dsc=], txt=, exp=, tr=null] weight=[Numerical Weight Value Dictating How Often this Button Was Used When Traversing the Application] ds=TR sc=[Path to Screen Shot of Transition]] ex=0
    Each line of the states section represents a screen accessible in the GUI structure of the application.
    Each state line follows this structure: [Screen Hash Number], [Idenitfying Behavior of Screen]]..., TR, [Screen XML Meta Data]

    === UNDERSTANDING MAPPING ===
    The mapping has 5 sections:
    1. triggering_screen_reference: A **single** screen hash from the application graph of the application screen the bug occured on
    2. triggering_GUI_interactions: One to many transition hash numbers from the application graph representing the user interaction(s) that trigger(s) the bug
    3. buggy_behavior: A description of the application behavior that occured following the triggering_GUI_interactions, as described by the user
    4. correct_behavior: A description of the application behavior that should have occured following the triggering_GUI_interactions, as described by the user
    5. steps_to_reproduce: A list of transition hash numbers from the application graph that represent a continuous path of GUI actions, connecting the opening screen of the application to the triggering_screen_reference, where the bug was experienced. Please include the triggering_GUI_interactions in this list. Each entry in the list should be a **single** transition hash number.
    Each section corresponds to an information element you might recieve. 
    Each entry in each section maps a part (triggering_GUI_interactions, steps_to_reproduce ) or all (triggering_screen_reference, buggy_behavior, correct_behavior) of the section to the graph. 
    Each entry comes with evidence, quotes from the information elements that informed the mapping, and a status, the confidence of the mapping, either ('unknown', 'ambiguous', 'inferred', 'confirmed'):
    'Confirmed': User evidence directly supports the mapped value (or near-paraphrase). No meaningful competing mapping.
    'Inferred': Mapped value is not directly stated, but is the single and most plausible conclusion from user evidence and context.
    'Ambiguous': User evidence is present but insufficiently specific; two or more plausible mappings remain. One tentative mapping has been chosen. For buggy behavior and correct behavior ambiguity refers to multiple plausible interpretations of described app behavior. For all other mappings, ambiguity refers to multiple plaussible state(screen)/transition(GUI action) hashes.
    'Unknown': No user evidence yet for this element.

    === UNDERSTANDING AMBIGUOUS AND UNKNOWN REFERENCE LIST ===
    If you see a list item of the form, 'steps_to_reproduce[i]' or 'triggering_gui_interactions[i]', that is specifying that the ith step to reproduce or ith triggering gui action respectfully, is ambiguous or unknown."
    If you see a either 'steps_to_reproduce' or 'triggering_gui_interactions', without an index, that means that the steps_to_reproduce or triggering_gui_interactions are entirely unknown.
    In all other scenarios, a list item specifies that the entire mapping for the information element is is ambiguous or unknown.

    Your task is to generate a **single** follow up question, guided by 'inferred' or 'confirmed' status previously collected information from the provided mapping and the structure of the application the bug appeard on defined by the application graph, to prompt a user to provide clarification on **one** ambiguous or unknown bug information fields.
    Please prioritize unknown status information over ambiguos information.
    Please return your follow up question in the format specified in the FollowUpSchema.
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template),
        (
            "human",
            "=== Application GUI Graph ===\n{app_graph}\n\n=== Previously Collected Information Mapping ===\n{previously_collected_information}\n\n=== Ambiguous and Unknown Reference List ===\n{ambiguous_and_unknown_reference_list}\n\n"
        )
    ])

    messages = prompt.format_messages(
        app_name=app_name,
        app_graph = app_graph,
        previously_collected_information = current_bug_info.model_dump_json(),
        ambiguous_and_unknown_reference_list=formatted_unknown_and_low_confidence_info
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

def extract_information_elements_from_OB_EB(observed_behavior : str, expected_behavior : str, model : Any):
    system_template = """
    # Task Summary

    You are an experienced Android application developer. Your task is to extract four information elements, i.e., **Buggy Behavior**,  **Triggering GUI Interactions**, **Triggering Screen References**, and **Correct Behavior**, from the given **Observed Behavior (OB)** and **Expected Behavior (EB)** of an Android app bug report.

    ---

    # You are provided with:

    - Definitions of the four **Information Elements** to extract.
    -  **Observed Behavior (OB)** and **Expected Behavior (EB)** of the bug report.

    ---

    # Definition of the Information Elements

    - **Buggy Behavior** (What buggy behavior is observed by the user?): The specific buggy behavior (i.e., the problem) reported in the bug.
    - **Triggering GUI Interactions** (What application interaction(/s) triggers the bug?): The user interaction(/s) on the application that triggers the bug.
    - **Triggering Screen References** (Which application screen causes the bug and/or where the bug was observed?): The application screen where performing the interaction causes the bug and/or the screen where the bug was observed.
    - **Correct Behavior** (What application behavior is expected by the user?): The specific correct application behavior that should happen instead of the buggy behavior.

    ---
    # Inputs

    - **OB**: {ob}
    - **EB**: {eb}

    ---
    # Instructions

    1. Analyze the given OB and EB descriptions.
    2. Extract **Buggy Behavior**,  **Triggering GUI Interactions**, and **Triggering Screen References** from OB by following the respective definitions. Split the OB description into three parts to write these three information elements.
    - Do not write duplicate phrases for these three elements.
    3. Extract **Correct Behavior** from EB by following the definition.
    4. Do not modify any text of OB and EB. Only extract the relevant phrases for each information element.
    5. Return the extracted information elements in the response following the response format.
    6. If any information element is not found, write “N/A”.

    ---

    # Response Format
    Return your response in the sturctured format defined by ObservedExpectedToInfoElements schema.
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template)
    
    ])

    messages = prompt.format_messages(
        ob = observed_behavior,
        eb = expected_behavior,
    )

    structured = model.with_structured_output(ObservedExpectedToInfoElements)

    extracted = structured.invoke(messages)

    return extracted.model_dump()


def generate_report(complete_bug_info: InfoSlots, app_graph: str, model: Any, app_name: str) -> str:
    """
    Generate High-Quality Textual Bug Report from Complete Bug InfoSlots
    """

    bug_info = process_bug_info(complete_bug_info)

    system_template = """
    # Task Summary
    You are an expert developer of Android applications. You are writing a report for bugs on {app_name}. Given information collected for a **user-experienced bug** on an android application, your task is to generate a **high-quality structured bug report** with four sections: **Title**, **Observed Behavior (OB)**, **Expected Behavior (EB)**, and **Steps to Reproduce (S2Rs)**. 

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
        app_name=app_name,
        bug_info = bug_info,
        app_graph = app_graph,
    )

    structured = model.with_structured_output(ReportGenerationSchema)

    output_bug_report = structured.invoke(messages)

    extracted_information_elements = extract_information_elements_from_OB_EB(observed_behavior=output_bug_report.observed_behavior, expected_behavior=output_bug_report.expected_behavior, model=model)

    return {
        "full_report": output_bug_report.model_dump(),
        "extracted_information_elements": extracted_information_elements,
    }

