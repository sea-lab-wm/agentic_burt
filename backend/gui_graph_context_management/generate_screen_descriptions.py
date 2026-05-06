from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

try:
    from .graph_data_parser import (
        get_screens_with_information_from_text,
        replace_simplified_screen_ids_with_original_ids,
    )
except ImportError:  # pragma: no cover - support direct script execution
    from graph_data_parser import (
        get_screens_with_information_from_text,
        replace_simplified_screen_ids_with_original_ids,
    )


SCREEN_DESCRIPTION_PROMPT_TEMPLATE = """
**Task Description**
You will be provided with a list of screens of an Android application with their UI screen and component information extracted from the application sources. Your task is to generate a clear description for each screen in 3 sentences. The description should include the UI elements visible to the user, with their functionality provided by the application on that particular screen. Use only the provided information for generating the descriptions. Return the screen with their descriptions according to the schema in the same order as the screens are presented in the input.

**List of screens with UI information**
{screens_with_information}
""".strip()


class ScreenDescriptionItem(BaseModel):
    screen_id: str = Field(description="Simplified screen identifier such as S1.")
    screen_name: str = Field(
        description="Screen name matching the provided graph information when available."
    )
    short_description: str = Field(
        description="Brief screen description in two sentences using only the supplied UI information."
    )


class ScreenDescriptionsOutput(BaseModel):
    screen_descriptions: list[ScreenDescriptionItem] = Field(
        default_factory=list,
        description="Descriptions for the provided screens.",
    )


def _format_screen_descriptions(output: ScreenDescriptionsOutput) -> str:
    lines = []
    for item in output.screen_descriptions:
        lines.append(f"{item.screen_id} - {item.screen_name}: {item.short_description}")
    return "\n".join(lines).strip()


def generate_screen_descriptions(graph_text: str, model: Any) -> str:
    screens_with_information, screen_id_map, _ = get_screens_with_information_from_text(graph_text)
    if not screens_with_information:
        return ""

    prompt = SCREEN_DESCRIPTION_PROMPT_TEMPLATE.format(
        screens_with_information="\n\n".join(screens_with_information)
    )
    structured_model = model.with_structured_output(ScreenDescriptionsOutput)
    structured_output = structured_model.invoke([HumanMessage(content=prompt)])
    screen_descriptions = _format_screen_descriptions(structured_output)
    if not screen_descriptions:
        return ""

    return replace_simplified_screen_ids_with_original_ids(screen_descriptions, screen_id_map)
