from __future__ import annotations

"""Structured LLM judge helpers used by the evaluator pipeline."""

from typing import Any, Literal

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from evaluator.prompts import INFO_ELEMENTS_JUDGE_PROMPT, S2R_JUDGE_PROMPT


class ObservedExpectedToInfoElements(BaseModel):
    """Structured extraction result for OB/EB -> information elements."""
    buggy_behavior: str
    triggering_gui_interactions: str
    triggering_screen_reference: str
    correct_behavior: str


QualityLabel = Literal["Correct", "Incomplete", "Ambiguous", "Missing", "Incorrect"]
S2RStepLabel = Literal["CS", "ES"]


class InfoElementsJudgeResult(BaseModel):
    """Structured output for the OB/EB information-element quality judge."""
    buggy_behavior: QualityLabel
    triggering_gui_interactions: QualityLabel
    triggering_screen_reference: QualityLabel
    correct_behavior: QualityLabel


class S2RStepJudgeResult(BaseModel):
    """One generated S2R step classification produced by the S2R judge."""
    generated_step: str = Field(description="One generated step-to-reproduce line.")
    label: S2RStepLabel = Field(description="Whether the generated step is correct or extra.")
    matched_gt_step: str = Field(
        description="The matched ground-truth step when label is CS, otherwise an empty string."
    )


class S2RJudgeResult(BaseModel):
    """Structured wrapped output for the S2R judge response."""
    steps: list[S2RStepJudgeResult] = Field(
        description="Per-generated-step S2R judgments returned by the judge."
    )


def extract_information_elements_from_OB_EB(observed_behavior: str, expected_behavior: str, model: Any) -> dict[str, str]:
    """Extract information elements from observed and expected behavior text.

    The evaluator derives these elements directly from the final generated bug
    report so downstream judging can compare a structured extraction against the
    CSV ground truth.
    """
    system_template = """# Task Summary:

    You are an experienced Android application developer. Your task is to extract four information elements, i.e., **Buggy Behavior**, **Triggering GUI Interactions**, **Triggering Screen References**, and **Correct Behavior**, from the given **Observed Behavior (OB)** and **Expected Behavior (EB)** of an Android app bug report.

    ---

    # You are provided with:

    - Definitions of the four **Information Elements** to extract.
    - **Observed Behavior (OB)** and **Expected Behavior (EB)** of the bug report.

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
    2. Extract **Buggy Behavior**, **Triggering GUI Interactions**, and **Triggering Screen References** from OB by following the respective definitions. Split the OB description into three parts to write these three information elements.
    - Do not write duplicate phrases for these three elements.
    3. Extract **Correct Behavior** from EB by following the definition.
    4. Do not modify any text of OB and EB. Only extract the relevant phrases for each information element.
    5. Return the extracted information elements in the response following the response format.
    6. If any information element is not found, write ""N/A"".

    ---

    # Response Format
    Return your response in the sturctured format defined by ObservedExpectedToInfoElements schema."""

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template),
    ])

    messages = prompt.format_messages(
        ob=observed_behavior,
        eb=expected_behavior,
    )

    structured = model.with_structured_output(ObservedExpectedToInfoElements)
    extracted = structured.invoke(messages)
    return extracted.model_dump()


def judge_information_elements(
    generated_info_elements: dict[str, str],
    ground_truth_info_elements: str,
    model: Any,
) -> InfoElementsJudgeResult:
    """Score information elements against CSV ground truth labels."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", INFO_ELEMENTS_JUDGE_PROMPT),
        ]
    )

    messages = prompt.format_messages(
        ground_truth_info_elements=ground_truth_info_elements,
        generated_info_elements=_format_info_elements(generated_info_elements),
    )

    structured = model.with_structured_output(InfoElementsJudgeResult)
    return structured.invoke(messages)


def judge_s2r(generated_s2rs: str, ground_truth_s2r: str, model: Any) -> S2RJudgeResult:
    """Judge generated steps-to-reproduce against ground-truth steps."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", S2R_JUDGE_PROMPT),
        ]
    )

    messages = prompt.format_messages(
        ground_truth_s2rs=ground_truth_s2r,
        generated_s2rs=generated_s2rs,
    )

    structured = model.with_structured_output(S2RJudgeResult)
    return structured.invoke(messages)


def _format_info_elements(info_elements: dict[str, str]) -> str:
    """Render structured information elements into the textual format used by the judge prompt."""
    return (
        f"Buggy Behavior: {info_elements.get('buggy_behavior', 'N/A')}\n"
        f"Triggering GUI Interactions: {info_elements.get('triggering_gui_interactions', 'N/A')}\n"
        f"Triggering Screen References: {info_elements.get('triggering_screen_reference', 'N/A')}\n"
        f"Correct Behavior: {info_elements.get('correct_behavior', 'N/A')}"
    )
