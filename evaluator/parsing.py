from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV_PATH = REPO_ROOT / "data" / "dev_set_info_element_gt_and_input_desc.csv"
LOG_FILENAME_PATTERN = re.compile(
    r"bug(?P<bug_id>\d+)_(?P<description_level>[A-Z]{1,2}C_[A-Z]{1,2}P)\.log$",
    re.IGNORECASE,
)


def discover_log_paths(inputs: Iterable[str]) -> list[Path]:
    """Resolve CLI inputs into a de-duplicated list of log files."""
    discovered: list[Path] = []

    for raw_input in inputs:
        path = Path(raw_input)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path = path.resolve()

        if path.is_file():
            if path.suffix.lower() == ".log":
                discovered.append(path)
            continue

        if path.is_dir():
            discovered.extend(sorted(path.rglob("*.log")))

    unique_paths = sorted(set(discovered))
    return unique_paths


def load_ground_truth_rows(csv_path: Path = DEFAULT_CSV_PATH) -> dict[int, dict[str, str]]:
    """Load the dev CSV once and index rows by bug_id for fast joins."""
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        rows: dict[int, dict[str, str]] = {}
        for row in reader:
            bug_id_raw = (row.get("bug_id") or "").strip()
            if not bug_id_raw:
                continue
            rows[int(bug_id_raw)] = row
    return rows


def parse_json_records(log_path: Path) -> list[dict[str, Any]]:
    """Parse the observability log's back-to-back JSON records."""
    text = log_path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    idx = 0
    records: list[dict[str, Any]] = []

    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1

        if idx >= len(text):
            break

        record, next_idx = decoder.raw_decode(text, idx)
        records.append(record)
        idx = next_idx

    return records


def extract_log_metadata(log_path: Path) -> dict[str, Any]:
    """Recover bug/run metadata encoded in the log path and filename."""
    relative_path = log_path.relative_to(REPO_ROOT)
    path_parts = relative_path.parts
    # For evaluator outputs we key results by the versioned log folder, e.g. logs/V2/.
    agent_version = path_parts[1] if len(path_parts) >= 2 and path_parts[0] == "logs" else "unknown"

    match = LOG_FILENAME_PATTERN.search(log_path.name)
    bug_id = int(match.group("bug_id")) if match else None
    description_level = match.group("description_level").upper() if match else None

    return {
        "log_path": str(relative_path),
        "log_file": log_path.name,
        "log_stem": log_path.stem,
        "agent_version": agent_version,
        "bug_id": bug_id,
        "description_level": description_level,
    }


def find_generate_report_action(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the final action that contains the generated bug report payload."""
    for record in records:
        actions = record.get("actions")
        if not isinstance(actions, list):
            continue

        for action in actions:
            if action.get("action_name") == "generate_report":
                return action
    return None


def build_log_context(log_path: Path, ground_truth_rows: dict[int, dict[str, str]]) -> dict[str, Any]:
    """Build the normalized evaluator input for one log file."""
    metadata = extract_log_metadata(log_path)
    records = parse_json_records(log_path)
    generate_report_action = find_generate_report_action(records)

    context: dict[str, Any] = {
        **metadata,
        "parse_status": "ok",
        "parse_error": None,
        "full_report": None,
        "logged_extracted_information_elements": None,
        "ground_truth": None,
        "app_name": None,
    }

    if generate_report_action is None:
        context["parse_status"] = "missing_generate_report"
        context["parse_error"] = "No generate_report action found in log."
        return context

    output = generate_report_action.get("output") or {}
    full_report = output.get("full_report")
    if not isinstance(full_report, dict):
        context["parse_status"] = "missing_full_report"
        context["parse_error"] = "generate_report action did not include a valid full_report object."
        return context

    context["full_report"] = full_report
    # Keep the logged extraction in the parser context for debugging and
    # future comparisons even though it is not written into the evaluation JSON.
    context["logged_extracted_information_elements"] = output.get("extracted_information_elements")

    bug_id = context.get("bug_id")
    if bug_id is not None:
        gt_row = ground_truth_rows.get(bug_id)
        if gt_row is not None:
            # Only carry the ground-truth fields needed by the current judges.
            context["ground_truth"] = {
                "bug_id": gt_row.get("bug_id"),
                "app_name": gt_row.get("app_name"),
                "info_elements_gt": gt_row.get("info_elements_gt"),
                "S2R_ground_truth": gt_row.get("S2R_ground_truth"),
            }
            context["app_name"] = gt_row.get("app_name")

    return context
