from pydantic import BaseModel, Field, StrictStr
from typing import List, Optional, Literal
from state import Slot

class ExtractionSchema(BaseModel):
    """
    Defines the structured ouput for LLM call in the extract_and_update phase/node, so that updated key bug information can be cleanly loaded into agent state
    """
    triggering_screen_reference: Optional[Slot] = Field(
        default=None,
        description=(
            "App graph screen hash representing the application screenwhere performing the interaction causes the bug and/or the screen where the bug was observed."
        ),
    )
    triggering_GUI_interactions: Optional[List[Slot]] = Field(
        default=None,
        description=(
            "App graph transition hashes representing user interaction(s) on the application that triggers the bug."
        ),
    )
    buggy_behavior: Optional[Slot] = Field(
        default=None,
        description=(
            "The specific buggy behavior (i.e., the problem) reported in the bug. "
            "Please use user's exact language where possible"
        ),
    )
    correct_behavior: Optional[Slot] = Field(
        default=None,
        description=(
            "The specific correct application behavior that should happen instead of the buggy behavior."
            "Please use user's exact language where possible"
        ),
    )
    steps_to_reproduce: Optional[List[Slot]] = Field(
        default=None,
        description=(
            "Ordered list of bug reproduction steps spanning app open to triggering_screen_reference. Each item is a Slot where value is one app graph transition hash number corresponding to one step to reproduce."
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

class ObservedExpectedToInfoElements(BaseModel):
    buggy_behavior: StrictStr
    triggering_gui_interactions: StrictStr
    triggering_screen_reference: StrictStr
    correct_behavior: StrictStr

class ClaritySchema(BaseModel):
    clarity_route : Literal["continue", "needs_clarification"] = Field(
        description="The model's clarity decision: 'continue' when extracted elements are clear, otherwise 'needs_clarification'."
    )
    clarity_issues: List[str] = Field(
        default_factory=list,
        description="List of clarity issues found in extracted information elements. Empty when clarity_route is 'continue'."
    )
