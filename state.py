from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, StrictStr
from typing import List, Optional, Annotated
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
                a. buggy_screen: screen hash of bug causing or bug manifesting screen
                b. trigger_action: transition hash of bug causing GUI interaction/action
                c. buggy_behavior: description of application behavior following the trigger_action
        EB Information:
                a. expected_behavior: description of what the user believes should be the resulting behavior of the trigger action
        S2Rs Information:
                a. steps_to_reproduce: a list of contiguous transition hashes from starting app screen to trigger_action
    """
    buggy_screen: Slot = Field(default_factory=Slot)
    trigger_action: Slot = Field(default_factory=Slot)
    buggy_behavior: Slot = Field(default_factory=Slot)
    expected_behavior: Slot = Field(default_factory=Slot)
    steps_to_reproduce: List[Slot] = Field(default_factory=list)

class BugAgentState(BaseModel):
    """
    Defines the final internal agent state/memory.
    In V1 Includes:
        messages: list of user descriptions of the bug they experienced
        BugInfo: see InfoSlots
        unknown_and_low_confidence_info: a set containing names of low confidence or unkwon info slots following the extract_and_update node that are used for generating follow up questions
        last_question: a string follow up question that is presented to the user during the interrupt_and_present node
        last_extraction_raw: the last llm_extraction, purely tracked for debugging purposes
    """ 
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)
    BugInfo: InfoSlots = Field(default_factory=InfoSlots)
    unknown_and_low_confidence_info: set[str] = Field(default_factory=set)
    generated_question: Optional[str] = None
    #last_extraction_raw: Optional[str] = None
