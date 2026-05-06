"""Structured-output schemas used by runtime LLM calls."""

from pydantic import BaseModel, Field, StrictStr
from typing import List, Optional, Literal
from .state import Slot

class ExtractionSchema(BaseModel):
    """Structured mapping update returned by the graph-grounding step."""
    triggering_screen_reference: Optional[Slot] = Field(
        default=None,
        description=(
            "Status plus candidate mappings for the application screen where performing the interaction causes the bug and/or the screen where the bug was observed. "
            "Use zero candidates for unknown, exactly one candidate for inferred or confirmed, and 2-3 ranked candidates for ambiguous."
        ),
    )
    triggering_GUI_interactions: Optional[List[Slot]] = Field(
        default=None,
        description=(
            "Status plus candidate mappings for user interaction(s) on the application that trigger the bug. "
            "Each item must follow the slot rules for unknown, inferred, confirmed, or ambiguous."
        ),
    )
    buggy_behavior: Optional[Slot] = Field(
        default=None,
        description=(
            "Status plus candidate mappings for the specific buggy behavior reported in the bug. "
            "Each candidate should use the user's exact language where possible."
        ),
    )
    correct_behavior: Optional[Slot] = Field(
        default=None,
        description=(
            "Status plus candidate mappings for the specific correct application behavior that should happen instead of the buggy behavior. "
            "Each candidate should use the user's exact language where possible."
        ),
    )
    steps_to_reproduce: Optional[List[Slot]] = Field(
        default=None,
        description=(
            "Ordered list of bug reproduction steps spanning app open to triggering_screen_reference. Each item is a slot containing candidate mappings for one app graph transition hash. "
            "Use zero candidates for unknown, exactly one candidate for inferred or confirmed, and 2-3 ranked candidates for ambiguous. "
            "If the user provides only part of the steps, include only those stated."
        ),
    )

class ClarityFollowUpSchema(BaseModel):
    """Structured output for clarity-focused follow-up generation."""

    follow_up_question: StrictStr = Field(
        description="A follow-up question that resolves clarity issues in extracted user information."
    )


class MoreInfoFollowUpSchema(BaseModel):
    """Structured output for missing-information follow-up generation."""

    follow_up_question: StrictStr = Field(
        description="A follow-up question that asks the user for missing or ambiguous bug information."
    )
    clarification_target_info_elements: List[StrictStr] = Field(
        default_factory=list,
        description=(
            "Flat list of whole information-element names targeted by the follow-up question."
        ),
    )

class ReportGenerationSchema(BaseModel):
    """Structured bug-report payload returned by final report generation."""
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

class ClaritySchema(BaseModel):
    """Structured clarity decision returned by the clarity-check step."""
    clarity_route : Literal["continue", "needs_clarification"] = Field(
        description="The model's clarity decision: 'continue' when extracted elements are clear, otherwise 'needs_clarification'."
    )
    clarity_issues: List[str] = Field(
        default_factory=list,
        description="List of clarity issues found in extracted information elements. Empty when clarity_route is 'continue'."
    )
