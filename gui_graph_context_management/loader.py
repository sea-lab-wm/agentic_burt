import json
from pathlib import Path
from typing import Any

#NOTE: Seems Clunky, but will work
CONTEXT_ROOT = Path(__file__).resolve().parent.parent / "gui_graph_context"


def _join_context_lines(value: Any) -> str | None:
    """Convert stored context content back into the runtime string format."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(line) for line in value)
    raise TypeError(f"Unsupported context value type: {type(value).__name__}")


def fetch_graph_data(bug_id: int) -> tuple[str | None, str | None, str | None]:
    """
    Fetch the application execution information necessary for reasoning on the
    current bug description from the matching ``gui_graph_context/bug<id>/context.json``.
    """
    context_path = CONTEXT_ROOT / f"bug{bug_id}" / "context.json"
    if not context_path.is_file():
        return None, None, None

    with context_path.open("r", encoding="utf-8") as context_file:
        payload = json.load(context_file)

    transitions = _join_context_lines(payload.get("transitions"))
    application_name = payload.get("application_name")
    screen_names_and_screen_descriptions = _join_context_lines(payload.get("screen_names_and_descriptions"))

    return transitions, application_name, screen_names_and_screen_descriptions


def list_active_bug_ids() -> list[int]:
    """
    Return bug ids whose GUI graph context is present and loadable enough for the
    runtime to start a conversation.
    """
    active_bug_ids: list[int] = []

    candidate_bug_ids: list[int] = []

    for bug_dir in CONTEXT_ROOT.glob("bug*"):
        if not bug_dir.is_dir():
            continue

        bug_id_text = bug_dir.name.removeprefix("bug")
        if not bug_id_text.isdigit():
            continue

        candidate_bug_ids.append(int(bug_id_text))

    for bug_id in sorted(candidate_bug_ids):
        try:
            transitions, app_name, _screen_descriptions = fetch_graph_data(bug_id=bug_id)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue

        if transitions and app_name:
            active_bug_ids.append(bug_id)

    return active_bug_ids
