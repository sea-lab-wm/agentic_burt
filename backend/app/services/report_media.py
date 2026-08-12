"""Resolve the GUI graph screenshots that a completed session's report refers to.

The agent never copies screenshots into the report; it references graph ids instead.
The triggering screen id lives in the session log (``triggering_screen_reference``) and
each reproduction step carries its graph edge id as a trailing ``<id>`` marker. Both are
turned into files under ``dataset/graphs_json_data_<DATASET>/Bug<id>/<app>/``.
"""

import re
from pathlib import Path
from typing import Any

import config
from app.schemas.sessions import ReportMediaResponse, ReportStepMedia
from app.services.burt_runtime import (
    InvalidSessionError,
    SessionNotFoundError,
    build_api_log_path,
)
from app.services.session_store import get_session
from observability.observability_sinks import parse_log_records

SCREENSHOT_ROOT = (
    Path(__file__).resolve().parents[2] / "dataset" / f"graphs_json_data_{config.DATASET}"
)

SCREEN_SCREENSHOT_KIND = "states"
TRANSITION_SCREENSHOT_KIND = "transitions"
SCREENSHOT_KINDS = (SCREEN_SCREENSHOT_KIND, TRANSITION_SCREENSHOT_KIND)

_SCREEN_REFERENCE_KEY = "triggering_screen_reference"
# User-edited reports are deliberately excluded: the editor strips the "<id>" markers,
# so only the agent-authored reports still carry the step to screenshot mapping.
_REPORT_KEYS = ("full_report", "draft_report")

# Graph node and edge ids are signed integers, so anything else is a traversal attempt.
_IMAGE_ID_PATTERN = re.compile(r"^-?\d+$")
_STEP_IDENTIFIER_PATTERN = re.compile(r"\s*<([^>\n]+)>\s*$")


def _collect_values(node: Any, keys: tuple[str, ...]) -> list[Any]:
    """Collect every value stored under one of ``keys``, in log document order."""
    collected: list[Any] = []

    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys:
                collected.append(value)
            else:
                collected.extend(_collect_values(value, keys))
    elif isinstance(node, list):
        for item in node:
            collected.extend(_collect_values(item, keys))

    return collected


def _screen_reference_value(reference: Any) -> str | None:
    """Read the screen id out of one triggering_screen_reference payload.

    Early extraction nodes store a bare ``{"value": ...}``; later ones store ranked
    ``candidates``, whose best-supported entry is listed first.
    """
    if isinstance(reference, str):
        return reference or None

    if isinstance(reference, dict):
        candidates = reference.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if isinstance(candidate, dict) and candidate.get("value") is not None:
                    return str(candidate["value"])

        value = reference.get("value")
        if value is not None:
            return str(value)

    return None


def _records_through_revision(
    records: list[dict[str, Any]],
    revision: int | None,
) -> list[dict[str, Any]]:
    """Cut the log off after the draft report of ``revision`` was written.

    A regenerated session holds several drafts, each grounded in its own run. Asking
    for one revision's media has to ignore everything the later runs went on to map,
    or every report card on screen would show the newest run's screenshots.
    """
    if revision is None:
        return records

    for position, record in enumerate(records):
        if record.get("record_type") != "draft_report":
            continue
        if record.get("revision", 1) == revision:
            return records[: position + 1]

    return records


def _latest_screen_id(records: list[dict[str, Any]]) -> str | None:
    """Return the most recent non-null triggering screen id recorded for the session."""
    for reference in reversed(_collect_values(records, (_SCREEN_REFERENCE_KEY,))):
        screen_id = _screen_reference_value(reference)
        if screen_id is not None:
            return screen_id

    return None


def _step_lines(steps_value: Any) -> list[str]:
    """Split a steps_to_reproduce payload into one line per step."""
    if isinstance(steps_value, str):
        lines = steps_value.split("\n")
    elif isinstance(steps_value, list):
        lines = [str(step) for step in steps_value]
    else:
        return []

    return [line for line in lines if line.strip()]


def _is_steps_to_reproduce_key(key: str) -> bool:
    """Match the steps field regardless of the separator style the report used."""
    return re.sub(r"[_-]", " ", key).strip().lower() == "steps to reproduce"


def _latest_report_step_lines(records: list[dict[str, Any]]) -> list[str]:
    """Return the newest agent-authored reproduction steps, graph ids still attached."""
    for report in reversed(_collect_values(records, _REPORT_KEYS)):
        if not isinstance(report, dict):
            continue

        for key, value in report.items():
            if not _is_steps_to_reproduce_key(key):
                continue

            lines = _step_lines(value)
            if lines:
                return lines

    return []


def resolve_app_directory(bug_id: int) -> Path | None:
    """Locate the screenshot directory of the single app captured for one bug."""
    for bug_directory_name in (f"Bug{bug_id}", f"bug{bug_id}"):
        bug_directory = SCREENSHOT_ROOT / bug_directory_name
        if not bug_directory.is_dir():
            continue

        for app_directory in sorted(bug_directory.iterdir()):
            if app_directory.is_dir():
                return app_directory

    return None


def _screenshot_file(
    app_directory: Path | None,
    kind: str,
    image_id: str | None,
) -> Path | None:
    """Return the captured screenshot for one graph id, or None when there is none.

    Not every graph element was captured: the synthetic "open app" transition, for
    instance, has no source screen to screenshot.
    """
    if app_directory is None or image_id is None or kind not in SCREENSHOT_KINDS:
        return None

    if not _IMAGE_ID_PATTERN.match(image_id):
        return None

    screenshot_path = app_directory / kind / f"{image_id}.png"
    return screenshot_path if screenshot_path.is_file() else None


def _build_steps(step_lines: list[str], app_directory: Path | None) -> list[ReportStepMedia]:
    """Split each step into its human text and the transition screenshot it maps to."""
    steps: list[ReportStepMedia] = []

    for index, line in enumerate(step_lines, start=1):
        identifier_match = _STEP_IDENTIFIER_PATTERN.search(line)
        transition_id = identifier_match.group(1).strip() if identifier_match else None
        text = (line[: identifier_match.start()] if identifier_match else line).strip()

        steps.append(
            ReportStepMedia(
                index=index,
                text=text,
                transition_id=transition_id,
                has_screenshot=_screenshot_file(
                    app_directory,
                    TRANSITION_SCREENSHOT_KIND,
                    transition_id,
                )
                is not None,
            )
        )

    return steps


def _session_bug_id(session_id: str) -> int:
    """Return the bug whose GUI graph backs one session's screenshots."""
    session_record = get_session(session_id)
    if session_record is None:
        raise SessionNotFoundError(f"Session {session_id} was not found.")

    bug_id = session_record.get("bug_id")
    if not isinstance(bug_id, int):
        raise InvalidSessionError(
            f"Session {session_id} is missing required report metadata."
        )

    return bug_id


def build_report_media(
    session_id: str,
    revision: int | None = None,
) -> ReportMediaResponse:
    """Describe which report fields have a screenshot the frontend can request.

    ``revision`` picks which of a regenerated session's drafts to answer for;
    without it the newest run wins.
    """
    bug_id = _session_bug_id(session_id)
    records = _records_through_revision(
        parse_log_records(build_api_log_path(session_id)),
        revision,
    )
    app_directory = resolve_app_directory(bug_id)
    screen_id = _latest_screen_id(records)

    return ReportMediaResponse(
        session_id=session_id,
        bug_id=bug_id,
        app_name=app_directory.name if app_directory is not None else None,
        screen_id=screen_id,
        has_screen_screenshot=_screenshot_file(
            app_directory,
            SCREEN_SCREENSHOT_KIND,
            screen_id,
        )
        is not None,
        steps=_build_steps(_latest_report_step_lines(records), app_directory),
    )


def resolve_screenshot(session_id: str, kind: str, image_id: str) -> Path | None:
    """Resolve one screenshot request against the bug graph recorded for a session."""
    return _screenshot_file(resolve_app_directory(_session_bug_id(session_id)), kind, image_id)
