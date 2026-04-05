from enum import Enum
from typing import Annotated, List, Literal, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, model_validator


class SlotStatus(str, Enum):
    """
    Confidence levels for the LLM's mapping of bug information.
    """

    unknown = "unknown"
    ambiguous = "ambiguous"
    inferred = "inferred"
    confirmed = "confirmed"


class CandidateMapping(BaseModel):
    """
    One possible mapping for a slot, paired with the evidence that supports it.
    Candidate order encodes ranking, with index 0 as the strongest fit.
    """

    value: str
    evidence: str


class Slot(BaseModel):
    """
    Defines structure of every information slot tracked by the internal bug report
    state. The slot stores only a status plus ranked candidate mappings.
    """

    status: SlotStatus = SlotStatus.unknown
    candidates: List[CandidateMapping] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_candidates_by_status(self) -> "Slot":
        count = len(self.candidates)

        if self.status == SlotStatus.unknown and count != 0:
            raise ValueError("Unknown slots must have an empty candidates list.")

        if self.status in {SlotStatus.inferred, SlotStatus.confirmed} and count != 1:
            raise ValueError("Inferred and confirmed slots must have exactly one candidate.")

        if self.status == SlotStatus.ambiguous and not 2 <= count <= 3:
            raise ValueError("Ambiguous slots must have 2-3 candidates.")

        return self


class InfoSlots(BaseModel):
    """
    Defines the key bug report information the agent seeks to gather during its
    conversation with the user.
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
    """

    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)
    BugInfo: InfoSlots = Field(default_factory=InfoSlots)
    information_element_extraction: InformationElementExtraction = Field(
        default_factory=InformationElementExtraction
    )
    clarity_issues: List[str] = Field(default_factory=list)
    clarity_route: Literal["continue", "needs_clarification"] = "continue"
    clarification_rounds: int = 0
    clarification_window_start_idx: int = 0
    unknown_and_low_confidence_info: set[str] = Field(default_factory=set)
    generated_question: Optional[str] = None
