from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


PromptTuple = tuple[str, str, str]
PromptVersionRecord = dict[str, Any]
DEFAULT_PROMPT_HISTORY_PATH = Path(__file__).with_name("prompt_versioning.json")


def load_prompt_history(
    json_path: str | Path = DEFAULT_PROMPT_HISTORY_PATH,
) -> list[PromptVersionRecord]:
    """
    Load the full JSON prompt version history.

    If the file does not exist yet, return an empty history.
    """

    path = Path(json_path)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as json_file:
        data = json.load(json_file)

    if not isinstance(data, list):
        raise ValueError("Prompt history JSON must contain a top-level list.")

    return data


def save_prompt_history(
    prompt_history: list[PromptVersionRecord],
    json_path: str | Path = DEFAULT_PROMPT_HISTORY_PATH,
) -> None:
    """Write the full JSON prompt version history to disk."""

    path = Path(json_path)
    with path.open("w", encoding="utf-8") as json_file:
        json.dump(prompt_history, json_file, indent=2, ensure_ascii=False)
        json_file.write("\n")


def upsert_prompts(
    prompt_updates: Iterable[PromptTuple],
    json_path: str | Path = DEFAULT_PROMPT_HISTORY_PATH,
) -> list[PromptVersionRecord]:
    """
    Add or update prompts in the JSON prompt version history.

    Each item in ``prompt_updates`` must be a 3-tuple in this order:
    ``(agent_version_title, prompt_name, prompt_text)``.

    If a version record does not exist yet, it is created automatically.
    If a prompt name already exists under a version, its text is replaced.
    """

    prompt_history = load_prompt_history(json_path)
    versions_by_title = {
        record["agent-version-title"]: record
        for record in prompt_history
        if isinstance(record, dict) and "agent-version-title" in record
    }

    for prompt_update in prompt_updates:
        agent_version_title, prompt_name, prompt_text = _validate_prompt_tuple(
            prompt_update
        )

        version_record = versions_by_title.get(agent_version_title)
        if version_record is None:
            version_record = {
                "agent-version-title": agent_version_title,
                "prompts": {},
            }
            prompt_history.append(version_record)
            versions_by_title[agent_version_title] = version_record

        prompts = version_record.setdefault("prompts", {})
        if not isinstance(prompts, dict):
            raise ValueError(
                f"Version '{agent_version_title}' has a non-dict 'prompts' field."
            )

        prompts[prompt_name] = prompt_text

    save_prompt_history(prompt_history, json_path)
    return prompt_history


def _validate_prompt_tuple(prompt_update: PromptTuple) -> PromptTuple:
    if len(prompt_update) != 3:
        raise ValueError(
            "Each prompt update must contain exactly 3 values: "
            "(agent-version-title, prompt-name, prompt-text)."
        )

    agent_version_title, prompt_name, prompt_text = prompt_update

    if not agent_version_title:
        raise ValueError("agent-version-title cannot be empty.")
    if not prompt_name:
        raise ValueError("prompt-name cannot be empty.")

    return agent_version_title, prompt_name, prompt_text


if __name__ == "__main__":
    prompts_to_upsert = [
        ("bugscribe_mutli-candidate_transitions_and_screen_descriptions",
         "map_to_graph",
         """# Task Summary
You are an expert developer of Android applications. Given **information elements** extracted from a **user description** of a bug on the **{application_name}** Android application, your task is to update/populate the fields of an **existing structured bug-report mapping** by grounding user-provided bug information in the application's GUI graph. The mapping will be used to generate a precise, application accurate and reproducible bug report.
 
#Context Overview
You will be provided with the following information:
1. The existing structured bug-report mapping that represents previously collected information from a conversation with the bug experiencing user mapped or cross referenced with states and edges on textual graph of application GUI structure. You can learn how to understand the structure of the mapping below in the UNDERSTANDING MAPPING section below.
2. A textual graph that models the GUI hierarchy of the application the bug occurred on. The graph has 2 parts: a set of app transitions that take users between app screens and a list of short descriptions and screen names for each app screen. You can learn how to understand the graph using the UNDERSTANDING APPLICATION GRAPH section below.
3. A labeled set of key bug report information elements extracted from a user description of a bug they experienced. You can learn more about the labels and how to understand given information elements in the UNDERSTANDING INFORMATION ELEMENTS section below.

#Understanding Each Provided Context
## UNDERSTANDING MAPPING 
The structured bug-report mapping has 5 sections that correspond to an information element you might receive:
1. triggering_screen_reference: A **single** screen hash from the application graph representing the application screen the bug occurred on.
2. triggering_GUI_interactions: One to many transition hash(es) from the application graph representing the user interaction(s) that trigger(s) the bug.
3. buggy_behavior: A description of the application behavior that occurred following the triggering_GUI_interactions, as described by the user.
4. correct_behavior: A description of the application behavior that should have occurred following the triggering_GUI_interactions, as described by the user.
5. steps_to_reproduce: A list of consecutive transition hash(es) from the application graph, starting at the applications opening screen and leading to the triggering_screen_reference. 

Each entry in the mapping comes with evidence, quotes from the extracted information elements that informed the previous mapping, and a status, the confidence of the mapping. The possible status labels and their definitions are: 
'Confirmed': User evidence directly supports the mapped value (or near-paraphrase). No meaningful competing mapping.
'Inferred': Mapped value is not directly stated, but is the single and most plausible conclusion from user evidence and context.
'Ambiguous': User evidence is present but insufficiently specific; two or three candidate mappings are provided. For buggy behavior and correct behavior ambiguity refers to multiple plausible interpretations of described app behavior. For all other entries, ambiguity refers to multiple plausible state(screen)/transition(GUI action) mappings.
'Unknown': No user evidence yet for this element. 'Unknown' status indicates that the user has not provided that information element yet.

## UNDERSTANDING APPLICATION GRAPH
The Application Graph is divided into 2 sections, transitions and a screen name and descriptions list.

Each line of the transitions section represents a GUI action or transition (button tap, swipe, etc.) that takes the user from a source application screen to a target application screen.
Each transition line follows this structure: [Transition Hash Number]: (s: [Source Screen Hash Number],t: [Target Screen Hash Number]): [id=0, ex=0, sq=1, act=(0) [Action Type (ie. click, tap, swipe)], cp=[, ty= [Component Type (ie. button, tab, image)], idx=[Component Name], idnx=1, tx=Component Text]], x=[Component Lateral Position on Screen]], y=[Component Vertical Position on Screen], h=[Component Height], w=[Component Width], dsc=], txt=, exp=, tr=null] weight=[Numerical Weight Value Dictating How Often this Button Was Used When Traversing the Application] ds=TR sc=[Path to Screen Shot of Transition]] ex=0. 
Transitions are separated into blocks by source screen. The first block of transitions will be open app transitions. 

Each screen hash in the transitions section has an entry in the screen name and descriptions list. The screen name and descriptions list follows this format:
[Screen Hash Number] - [Screen Name]: [Screen Description]

## UNDERSTANDING INFORMATION ELEMENTS
 There are 5 possible information elements you can receive at any given time:
1. triggering_screen_reference: The application screen where performing the interaction causes the bug and/or the screen where the bug was observed.
2. triggering_GUI_interactions: The user interaction(s) on the application that triggers the bug.
3. buggy_behavior: The specific buggy behavior (the problem) reported in the bug.
4. correct_behavior: The specific correct behavior that should happen instead of the buggy behavior.
5. steps_to_reproduce: A contiguous sequence of application interactions starting from app launch and ending at the triggering screen.

# Specific Constraints on Updating Sections of the Mapping
## triggering_screen_reference
If you can confirm the **buggy_behavior** or **expected_behavior** you must attempt to locate the **triggering_screen_reference** from the screens in the application graph.
## buggy_behavior 
If you can confirm the **buggy_behavior**, you must attempt to generate the **correct_behavior**.
## correct_behavior
If you can confirm the **correct_behavior**,  you must attempt to generate the **buggy_behavior**.
## steps_to_reproduce:
Always *start* with opening the application.
Include the triggering_GUI_interactions.
Each entry in the list should be a **single** transition hash number.
If the triggering_screen_reference occurs at an intermediate step, do **not** stop there, continue generating the **full sequence of steps** required to reproduce the bug.
The **target screen** of one S2R must be the **source screen** of the next.
**Do not include** any steps that are not interactions or are not backed by a valid transition (e.g., \"observe the error\").

# General Constraints
Do not hallucinate or introduce details not present in the context.
Maintain language clarity, precision, and consistency 
Once a status of 'confirmed' is assigned to an entry in the mapping, the entry CAN NOT be changed
Ambiguous status is reserved for situations when there are 2-3 strong, evidence-backed alternatives for a specific mapping entry based on user wording. If user wording leaves more than 3 plausible candidates, 'unknown' status should be used.
Mapping entries assigned Ambiguous status must have 2-3 candidates MAXIMUM.

# Output Format
Generate according to the provided schema
""")
    ]
    upsert_prompts(prompts_to_upsert)
