from state import (
    BugAgentState,
    CandidateMapping,
    InfoSlots,
    InformationElementExtraction,
    Slot,
    SlotStatus,
)
from llm_schema import (
    ClarityFollowUpSchema,
    ClaritySchema,
    ExtractionSchema,
    MoreInfoFollowUpSchema,
    ReportGenerationSchema,
)
from langchain_core.prompts import ChatPromptTemplate
from typing import Any, Literal
from functools import lru_cache
from pathlib import Path
import json
from config import PROMPT_VERSION


PROMPT_VERSIONING_JSON = Path(__file__).with_name("prompt_versioning") / "prompt_versioning.json"


@lru_cache(maxsize=1)
def _load_prompt_records() -> list[dict[str, Any]]:
    with PROMPT_VERSIONING_JSON.open("r", encoding="utf-8") as json_file:
        prompt_records = json.load(json_file)

    if not isinstance(prompt_records, list):
        raise ValueError(
            f"Prompt version file {PROMPT_VERSIONING_JSON} must contain a top-level list."
        )

    return prompt_records


def _load_prompt_record(version: str | int | None = PROMPT_VERSION) -> dict[str, Any]:
    prompt_records = _load_prompt_records()
    if not prompt_records:
        raise ValueError(f"No prompt versions were found in {PROMPT_VERSIONING_JSON}.")

    if len(prompt_records) == 1:
        return prompt_records[0]

    if isinstance(version, str):
        for record in prompt_records:
            if record.get("agent-version-title") == version:
                return record
    elif isinstance(version, int):
        zero_based_index = version - 1
        if 0 <= zero_based_index < len(prompt_records):
            return prompt_records[zero_based_index]

        version_as_title = str(version)
        for record in prompt_records:
            if record.get("agent-version-title") == version_as_title:
                return record

    raise ValueError(
        f"Prompt version {version!r} was not found in {PROMPT_VERSIONING_JSON}."
    )


def load_prompt_template(prompt_key: str, version: str | int | None = PROMPT_VERSION) -> str:
    prompt_record = _load_prompt_record(version)
    prompts = prompt_record.get("prompts")
    if not isinstance(prompts, dict):
        raise ValueError(
            f"Prompt version record {prompt_record.get('agent-version-title')!r} "
            f"in {PROMPT_VERSIONING_JSON} is missing a valid 'prompts' mapping."
        )

    prompt_template = prompts.get(prompt_key)
    if not isinstance(prompt_template, str) or not prompt_template:
        version_title = prompt_record.get("agent-version-title")
        raise ValueError(
            f"Prompt key '{prompt_key}' was not found for version {version_title!r} "
            f"in {PROMPT_VERSIONING_JSON}."
        )
    return prompt_template

def llm_extract(
    user_messages: list[str],
    model: Any,
    app_name: str,
    follow_up_question: str | None = None,
    target_info_elements: list[str] | None = None,
    extraction_mode: Literal["initial", "more_info_follow_up", "clarity_follow_up"] = "initial",
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
    :param target_info_elements: flat list of targeted info elements for more-info follow-ups
    :type target_info_elements: list[str] | None
    :param extraction_mode: whether input text is an initial description or a specific follow-up response
    :type extraction_mode: Literal["initial", "more_info_follow_up", "clarity_follow_up"]
    :return: extracted natural language information elements
    :rtype: InformationElementExtraction
    """

    system_template = load_prompt_template("information_element_extraction")
    user_messages_text = "\n".join(f"- {message}" for message in user_messages)

    if extraction_mode == "initial":
        human_template = (
            "Extraction mode: {extraction_mode}\n\n"
            "User descriptions:\n{user_messages}"
        )
        format_kwargs = {
            "app_name": app_name,
            "extraction_mode": extraction_mode,
            "user_messages": user_messages_text,
        }
    elif extraction_mode == "clarity_follow_up":
        if follow_up_question is None:
            raise ValueError(
                "follow_up_question is required for clarity_follow_up extraction mode."
            )
        human_template = (
            "Extraction mode: {extraction_mode}\n"
            "Follow-up question:\n{follow_up_question}\n\n"
            "User descriptions:\n{user_messages}"
        )
        format_kwargs = {
            "app_name": app_name,
            "extraction_mode": extraction_mode,
            "follow_up_question": follow_up_question,
            "user_messages": user_messages_text,
        }
    elif extraction_mode == "more_info_follow_up":
        if follow_up_question is None:
            raise ValueError(
                "follow_up_question is required for more_info_follow_up extraction mode."
            )
        human_template = (
            "Extraction mode: {extraction_mode}\n"
            "Follow-up question:\n{follow_up_question}\n"
            "Target info elements:\n{target_info_elements}\n\n"
            "User descriptions:\n{user_messages}"
        )
        format_kwargs = {
            "app_name": app_name,
            "extraction_mode": extraction_mode,
            "follow_up_question": follow_up_question,
            "target_info_elements": ", ".join(target_info_elements or []),
            "user_messages": user_messages_text,
        }
    else:
        raise ValueError(f"Unsupported extraction_mode: {extraction_mode!r}")

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_template),
            ("human", human_template),
        ]
    )

    formatted_messages = prompt.format_messages(**format_kwargs)

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

    system_template = load_prompt_template("clarity_check")

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


def is_unresolved_slot(slot: Slot) -> bool:
    return slot.status in {SlotStatus.unknown, SlotStatus.ambiguous}


def get_resolved_candidate(slot: Slot, field_name: str) -> CandidateMapping:
    if slot.status not in {SlotStatus.inferred, SlotStatus.confirmed}:
        raise ValueError(
            f"{field_name} must be resolved before use; got status={slot.status.value!r}."
        )

    return slot.candidates[0]


def stringify_slot(slot: Slot) -> str:
    return json.dumps(
        {
            "status": slot.status.value,
            "candidates": [candidate.model_dump() for candidate in slot.candidates],
        }
    )


def format_bug_info_for_prompt(info: InfoSlots) -> str:
    sections = []

    for name, content in info:
        title = name.replace("_", " ").title()
        if name in {"steps_to_reproduce", "triggering_GUI_interactions"}:
            lines = [f"{title}:"]
            if not content:
                lines.append("- []")
            else:
                for i, slot in enumerate(content):
                    lines.append(f"- [{i}] {stringify_slot(slot)}")
            sections.append("\n".join(lines))
        else:
            sections.append(f"{title}:\n- {stringify_slot(content)}")

    return "\n\n".join(sections)


def _reference_label(field_name: str) -> str:
    if field_name == "triggering_GUI_interactions":
        return "triggering_gui_interactions"
    return field_name


def format_unknown_or_ambiguous_references(
    info: InfoSlots,
    references: set[str] | list[str],
) -> ClarityFollowUpSchema:
    """
    Format unresolved mapping references as an ordered, user-model-facing list.

    Unknown entries are listed before ambiguous entries to match the updated
    follow-up prompt priority guidance. Reference labels are normalized to the
    prompt's expected naming convention.
    """

    formatted_entries: list[tuple[int, str]] = []

    for reference in references:
        base_name, has_index, suffix = reference.partition("[")
        prompt_name = _reference_label(base_name)
        prompt_reference = f"{prompt_name}[{suffix}" if has_index else prompt_name

        content = getattr(info, base_name)
        if has_index:
            index = int(suffix[:-1])
            status = content[index].status
        else:
            status = content.status if isinstance(content, Slot) else SlotStatus.unknown

        priority = 0 if status == SlotStatus.unknown else 1
        formatted_entries.append((priority, prompt_reference))

    formatted_entries.sort(key=lambda item: (item[0], item[1]))
    return "\n".join(f"- {reference}" for _, reference in formatted_entries)

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
    :return: structured follow-up question(s) to resolve clarity issues
    :rtype: ClarityFollowUpSchema
    """

    system_template = load_prompt_template("clarity_follow_up")

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

    structured = model.with_structured_output(ClarityFollowUpSchema)
    return structured.invoke(messages)

def llm_map(
    current_bug_info: InfoSlots,
    app_graph: str,
    screen_name_and_description_list: str,
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

    system_template = load_prompt_template("map_to_graph")

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template),
        (
            "human",
            "#Context:\n\n ##Structured Bug Report Mapping:\n{structured_bug_report_mapping}\n\n ##Application GUI Graph\n###Transitions:\n{transitions}\n###Screen Name and Description List:\n{screen_name_and_description_list}\n\n##Extracted Information Elements:\n{extracted_information_elements}\n\n"
        )
    ])

    messages = prompt.format_messages(
        application_name=app_name,
        transitions = app_graph,
        screen_name_and_description_list = screen_name_and_description_list,
        structured_bug_report_mapping = format_bug_info_for_prompt(current_bug_info),
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
    Maintains current InfoSlots if LLM does not add them in its updated mapping,
    then clears transient natural-language extraction state after mapping.
    
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
        "information_element_extraction": InformationElementExtraction(),
        "clarification_window_start_idx": len(state.messages),
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
                if is_unresolved_slot(step):
                    flagged.add(f"{name}[{i}]")
        else:
            if is_unresolved_slot(content):
                flagged.add(name)

    return flagged

def llm_more_info_follow_up(
    current_bug_info: InfoSlots,
    app_graph: str,
    screen_name_and_description_list: str,
    formatted_unknown_and_low_confidence_info: str,
    model: Any,
    app_name: str,
) -> MoreInfoFollowUpSchema:

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
    :return: Structured follow-up output containing question text and targeted info elements
    :rtype: MoreInfoFollowUpSchema
    """

    system_template = load_prompt_template("more_info_follow_up")

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template),
        (
            "human",
            "#Context:\n\n##Structured Bug Report Mapping:\n{previously_collected_information}\n\n##Application GUI Graph\n###Transitions:\n{transitions}\n###Screen Name and Description List:\n{screen_name_and_description_list}\n\n##Ambiguous and Unknown Reference List:\n{ambiguous_and_unknown_reference_list}\n"
        )
    ])

    messages = prompt.format_messages(
        application_name=app_name,
        transitions=app_graph,
        screen_name_and_description_list=screen_name_and_description_list,
        previously_collected_information = format_bug_info_for_prompt(current_bug_info),
        ambiguous_and_unknown_reference_list=formatted_unknown_and_low_confidence_info
    )

    structured = model.with_structured_output(MoreInfoFollowUpSchema)

    return structured.invoke(messages)

def validate_info_status(complete_bug_info : InfoSlots) -> None:
    """
    Validate that all bug-info slots are fully resolved before downstream use.

    :param complete_state: Completed BugAgentState object
    :type complete_state: BugAgentState
    """
    get_resolved_candidate(
        complete_bug_info.triggering_screen_reference,
        "triggering_screen_reference",
    )
    for interaction in complete_bug_info.triggering_GUI_interactions:
        get_resolved_candidate(interaction, "triggering_GUI_interactions")
    get_resolved_candidate(
        complete_bug_info.buggy_behavior,
        "buggy_behavior",
    )
    get_resolved_candidate(
        complete_bug_info.correct_behavior,
        "correct_behavior",
    )
    for step in complete_bug_info.steps_to_reproduce:
        get_resolved_candidate(step, "steps_to_reproduce")

def generate_report(complete_bug_info: InfoSlots, app_graph: str, model: Any, app_name: str) -> str:
    """
    Generate High-Quality Textual Bug Report from Complete Bug InfoSlots
    """

    validate_info_status(complete_bug_info)
    structured_bug_report_mapping = format_bug_info_for_prompt(complete_bug_info)

    system_template = load_prompt_template("generate_report")

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template),
        (
            "human",
            "#Context:\n\n##Structured Bug Report Mapping:\n{structured_bug_report_mapping}\n\n##Application GUI Graph\n{app_graph}\n"
        ),
    ])

    messages = prompt.format_messages(
        app_name=app_name,
        structured_bug_report_mapping = structured_bug_report_mapping,
        app_graph = app_graph,
    )

    structured = model.with_structured_output(ReportGenerationSchema)

    output_bug_report = structured.invoke(messages)

    return {"full_report": output_bug_report.model_dump()}
