from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional, Annotated, Literal
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class SlotStatus(str, Enum):
    """
    #Defines onfidence levels for the LLM's extraction of key information from the users bug descriptions
    """
    unknown = "unknown"
    ambiguous = "ambiguous"
    inferred = "inferred"
    confirmed = "confirmed"

class Slot(BaseModel):
    """
    Defines structure of every information slot tracked by the internal bug report state.
    Each information slot comes with: 
        1. a value: the LLMs map from user description to a Graph Hash or OB/EB descriptionb) 
        2. a confidence level: see SlotStatus
        3. evidence: a short string providing evidence for why the LLM selected the value based on the user's description
    """
    value: Optional[str] = None
    status: SlotStatus = SlotStatus.unknown
    evidence: Optional[str] = None 

class InfoSlots(BaseModel):
    """
    Defines the key bug report information that are agent seeks to gather information on during its conversation with the user.
    V1 InfoSlots:
        OB Information: 
                a. triggering_screen_reference: The application screen where performing the interaction causes the bug and/or the screen where the bug was observed.
                b. triggering_GUI_interactions: The user interaction(s) on the application that triggers the bug. These interactions may consist of a single action or a short sequence of causally important actions and do NOT need to be the final step in the Steps to Reproduce.
                c. buggy_behavior: The specific buggy behavior (i.e., the problem) reported in the bug.
        EB Information:
                a. correct_behavior: The specific correct application behavior that should happen instead of the buggy behavior.
        S2Rs Information:
                a. steps_to_reproduce: a list of contiguous transition hashes from starting app screen to triggering_screen_reference, representing the users path through the application resulting in the bug being experienced.
    """
    triggering_screen_reference: Slot = Field(default_factory=Slot)
    triggering_GUI_interactions: List[Slot] = Field(default_factory=list)
    buggy_behavior: Slot = Field(default_factory=Slot)
    correct_behavior: Slot = Field(default_factory=Slot)
    steps_to_reproduce: List[Slot] = Field(default_factory=list)

class NaturalLanguageElement(BaseModel):
    """
    Defines a single extracted natural language information element.
    This model is used before graph mapping and preserves exactly what the user stated.
    """
    value: str
    evidence: List[str] = Field(default_factory=list)

class InformationElementExtraction(BaseModel):
    """
    Stores extracted natural language information elements from the user message window.
    Each field is optional and only populated when the user provides content for that element.
    """
    triggering_screen_reference: Optional[NaturalLanguageElement] = None
    triggering_GUI_interactions: Optional[NaturalLanguageElement] = None
    buggy_behavior: Optional[NaturalLanguageElement] = None
    correct_behavior: Optional[NaturalLanguageElement] = None
    steps_to_reproduce: Optional[NaturalLanguageElement] = None

class BugAgentState(BaseModel):
    """
    Defines the final internal agent state/memory.
    Includes:
        messages: ordered user responses collected during the conversation.
        BugInfo: grounded and confidence-scored bug information slots (see InfoSlots).
        information_element_extraction: pre-mapping natural language extraction output.
            Each populated element contains a required aggregated value and evidence list.
        clarity_issues: short issue strings from clarity_check describing unclear elements.
        clarity_route: clarity_check routing decision ("continue" or "needs_clarification").
        clarification_rounds: number of clarification attempts in the active clarification loop.
        clarification_window_start_idx: message index where the active clarification loop started.
        unknown_and_low_confidence_info: low-confidence/unknown grounded slots used by follow_up.
        generated_question: latest agent question shown by interrupt_and_present.
    """ 
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)
    BugInfo: InfoSlots = Field(default_factory=InfoSlots)
    information_element_extraction: InformationElementExtraction = Field(default_factory=InformationElementExtraction)
    clarity_issues: List[str] = Field(default_factory=list)
    clarity_route: Literal["continue", "needs_clarification"] = "continue"
    clarification_rounds: int = 0
    clarification_window_start_idx: int = 0
    unknown_and_low_confidence_info: set[str] = Field(default_factory=set)
    generated_question: Optional[str] = None
