from pydantic import BaseModel, Field, StrictStr
from typing import List, Optional
from state import Slot

class ExtractionSchema(BaseModel):
    """
    Defines the structured ouput for LLM call in the extract_and_update phase/node, so that updated key bug information can be cleanly loaded into agent state
    """
    buggy_screen: Optional[Slot] = Field(
        default=None,
        description=(
            "The screen/view hash of the screen where the bug occurs. "
        ),
    )
    trigger_action: Optional[Slot] = Field(
        default=None,
        description=(
            "The transition hash of the application action or transition that triggers the bug. "
        ),
    )
    buggy_behavior: Optional[Slot] = Field(
        default=None,
        description=(
            "What actually happened (the observed buggy behavior). "
            "Please use user's exact language where possible"
        ),
    )
    expected_behavior: Optional[Slot] = Field(
        default=None,
        description=(
            "What the user expected to happen instead. "
            "Please use user's exact language where possible"
        ),
    )
    steps_to_reproduce: Optional[List[Slot]] = Field(
        default=None,
        description=(
            "Ordered list of reproduction steps. Each item is a Slot where value is one transition hash number"
            "If the user provides only part of the steps, include only those stated."
        ),
    )

class FollowUpSchema(BaseModel):
    """
    Defines the structured ouput for LLM call in the follow_up phase/node, so that generated follow up question can be cleanly loaded into agent state
    """
    follow_up_question : StrictStr = Field(
        description=(
            "A follow up question that prompts to the user to provide calrifying information about low_confidence or missing status bug info"
        ),
    )

class ReportGenerationSchema(BaseModel):
    title : StrictStr = Field(
        description="The title of the generated bug report"
    )
    observed_behavior : StrictStr = Field(
        description="The observed behavior section of the generated bug report"
    )
    expected_behavior : StrictStr = Field(
        description="The expected behavior section of the generated bug report"
    )
    steps_to_reproduce : StrictStr = Field(
        description="The steps to reproduce section of the generated bug report"
    )