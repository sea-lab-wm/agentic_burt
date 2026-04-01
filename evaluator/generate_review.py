from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, PatternFill

from evaluator.parsing import REPO_ROOT, load_ground_truth_rows


RESULTS_ROOT = REPO_ROOT / "Results"
S2R_REVIEW_WORKBOOK = "s2r_manual_review.xlsx"
INFO_ELEMENTS_REVIEW_WORKBOOK = "information_elements_manual_review.xlsx"
SEPARATOR_FILL = PatternFill(fill_type="solid", fgColor="D9D9D9")


def rebuild_summary_csv(agent_version: str) -> Path:
    """Regenerate the version-local summary CSV from evaluation JSON files."""
    version_dir = RESULTS_ROOT / agent_version
    summary_path = version_dir / "summary.csv"
    evaluation_paths = sorted(version_dir.glob("*.evaluation.json"))

    fieldnames = [
        "bug_id",
        "description_level",
        "agent_version",
        "log_file",
        "log_path",
        "title",
        "status",
        "parse_status",
        "error",
    ]

    with summary_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for evaluation_path in evaluation_paths:
            result = json.loads(evaluation_path.read_text(encoding="utf-8"))
            writer.writerow(
                {
                    "bug_id": result.get("bug_id"),
                    "description_level": result.get("description_level"),
                    "agent_version": result.get("agent_version"),
                    "log_file": Path(result.get("log_path", "")).name,
                    "log_path": result.get("log_path"),
                    "title": result.get("title"),
                    "status": result.get("status"),
                    "parse_status": result.get("parse_status"),
                    "error": result.get("error"),
                }
            )

    return summary_path


def rebuild_s2r_review_workbook(agent_version: str) -> Path:
    """Build a manual-review workbook for S2R judge outputs."""
    version_dir = RESULTS_ROOT / agent_version
    workbook_path = version_dir / S2R_REVIEW_WORKBOOK
    evaluation_paths = sorted(version_dir.glob("*.evaluation.json"))
    ground_truth_rows = load_ground_truth_rows()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "S2R Review"
    headers = [
        "bug_id",
        "app_name",
        "agent_version",
        "description_level",
        "description_text",
        "full_bug_report",
        "s2r_gt",
        "agent_generated_steps",
        "LLM_evaluation",
        "Matched_GT_by_LLM",
        "human_evaluation",
        "Precision",
        "Recall",
    ]
    sheet.append(headers)
    sheet.freeze_panes = "A2"

    for column, width in {
        "A": 10,
        "B": 22,
        "C": 16,
        "D": 18,
        "E": 60,
        "F": 60,
        "G": 60,
        "H": 60,
        "I": 16,
        "J": 60,
        "K": 18,
        "L": 14,
        "M": 14,
    }.items():
        sheet.column_dimensions[column].width = width

    next_row = 2
    for evaluation_index, evaluation_path in enumerate(evaluation_paths):
        result = json.loads(evaluation_path.read_text(encoding="utf-8"))
        bug_id = result.get("bug_id")
        description_level = result.get("description_level")
        gt_row = ground_truth_rows.get(bug_id) if isinstance(bug_id, int) else None
        s2r_rows = result.get("s2r_judge")
        block_rows = s2r_rows if isinstance(s2r_rows, list) and s2r_rows else [None]
        block_start = next_row
        block_end = block_start + len(block_rows) - 1
        gt_text = ((result.get("ground_truth") or {}).get("S2R_ground_truth") or "").strip()
        gt_count = _count_numbered_steps(gt_text)

        for index, step in enumerate(block_rows):
            row_number = block_start + index
            row_values = [
                bug_id if index == 0 else "",
                result.get("app_name") if index == 0 else "",
                result.get("agent_version") if index == 0 else "",
                description_level if index == 0 else "",
                _lookup_description_text(gt_row, description_level) if index == 0 else "",
                _build_full_bug_report_text(result) if index == 0 else "",
                gt_text if index == 0 else "",
                (step or {}).get("generated_step", ""),
                (step or {}).get("label", ""),
                (step or {}).get("matched_gt_step", ""),
                (step or {}).get("label", ""),
                _build_precision_formula(block_start, block_end) if index == 0 else "",
                _build_recall_formula(block_start, block_end, gt_count) if index == 0 else "",
            ]
            sheet.append(row_values)
            for cell in sheet[row_number]:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

        next_row = block_end + 1
        if evaluation_index < len(evaluation_paths) - 1:
            _append_separator_row(sheet, len(headers), next_row)
            next_row += 1

    workbook.save(workbook_path)
    return workbook_path


def rebuild_info_elements_review_workbook(agent_version: str) -> Path:
    """Build a manual-review workbook for information-elements judge outputs."""
    version_dir = RESULTS_ROOT / agent_version
    workbook_path = version_dir / INFO_ELEMENTS_REVIEW_WORKBOOK
    evaluation_paths = sorted(version_dir.glob("*.evaluation.json"))
    ground_truth_rows = load_ground_truth_rows()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Info Elements Review"
    headers = [
        "bug_id",
        "app_name",
        "agent_version",
        "description_level",
        "description_text",
        "full_generated_bug_report",
        "info_elements_gt",
        "agent_generated_info_elements",
        "buggy_behavior_grade",
        "triggering_gui_interactions_grade",
        "triggering_screen_reference_grade",
        "correct_behavior_grade",
    ]
    sheet.append(headers)
    sheet.freeze_panes = "A2"

    for column, width in {
        "A": 10,
        "B": 22,
        "C": 16,
        "D": 18,
        "E": 60,
        "F": 60,
        "G": 60,
        "H": 60,
        "I": 20,
        "J": 26,
        "K": 26,
        "L": 20,
    }.items():
        sheet.column_dimensions[column].width = width

    next_row = 2
    for evaluation_index, evaluation_path in enumerate(evaluation_paths):
        result = json.loads(evaluation_path.read_text(encoding="utf-8"))
        bug_id = result.get("bug_id")
        description_level = result.get("description_level")
        gt_row = ground_truth_rows.get(bug_id) if isinstance(bug_id, int) else None
        info_judge = result.get("info_elements_judge")
        row_values = [
            bug_id,
            result.get("app_name"),
            result.get("agent_version"),
            description_level,
            _lookup_description_text(gt_row, description_level),
            _build_full_bug_report_text(result),
            ((result.get("ground_truth") or {}).get("info_elements_gt") or "").strip(),
            _format_agent_generated_info_elements(result.get("recomputed_info_elements")),
            info_judge.get("buggy_behavior", "") if isinstance(info_judge, dict) else "",
            info_judge.get("triggering_gui_interactions", "") if isinstance(info_judge, dict) else "",
            info_judge.get("triggering_screen_reference", "") if isinstance(info_judge, dict) else "",
            info_judge.get("correct_behavior", "") if isinstance(info_judge, dict) else "",
        ]
        sheet.append(row_values)
        for cell in sheet[next_row]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

        next_row += 1
        if evaluation_index < len(evaluation_paths) - 1:
            _append_separator_row(sheet, len(headers), next_row)
            next_row += 1

    workbook.save(workbook_path)
    return workbook_path


def _lookup_description_text(gt_row: dict[str, str] | None, description_level: str | None) -> str:
    """Resolve the input description text for the bug/description pair from the dev CSV."""
    if not gt_row or not description_level:
        return ""
    column_name = f"{description_level} Desc"
    return (gt_row.get(column_name) or "").strip()


def _build_full_bug_report_text(result: dict[str, Any]) -> str:
    """Compose a consistent generated bug report text block."""
    full_report = result.get("full_report") or {}
    parts = [
        ("Title", full_report.get("title")),
        ("Observed Behavior", full_report.get("observed_behavior")),
        ("Expected Behavior", full_report.get("expected_behavior")),
    ]
    return "\n\n".join(f"{label}: {value}" for label, value in parts if value)


def _format_agent_generated_info_elements(info_elements: dict[str, str] | None) -> str:
    """Render generated information elements into a manual-review text block."""
    if not info_elements:
        return ""

    parts = [
        ("Buggy Behavior", info_elements.get("buggy_behavior")),
        ("Triggering GUI Interactions", info_elements.get("triggering_gui_interactions")),
        ("Triggering Screen Reference", info_elements.get("triggering_screen_reference")),
        ("Correct Behavior", info_elements.get("correct_behavior")),
    ]
    return "\n".join(f"{label}: {value}" for label, value in parts if value)


def _build_precision_formula(start_row: int, end_row: int) -> str:
    """Build the per-block precision formula from the human evaluation column."""
    return f'=IFERROR(COUNTIF(K{start_row}:K{end_row},"CS")/COUNTA(K{start_row}:K{end_row}),"")'


def _build_recall_formula(start_row: int, end_row: int, gt_count: int) -> str:
    """Build the per-block recall formula from the human evaluation column."""
    if gt_count <= 0:
        return ""
    return f'=COUNTIF(K{start_row}:K{end_row},"CS")/{gt_count}'


def _count_numbered_steps(steps_text: str) -> int:
    """Count numbered S2R lines in the ground-truth CSV format."""
    return sum(
        1
        for line in steps_text.splitlines()
        if line.strip() and line.lstrip().split(".", 1)[0].isdigit()
    )


def _append_separator_row(sheet: Any, column_count: int, row_number: int) -> None:
    """Insert a blank gray spacer row between review blocks."""
    sheet.append([""] * column_count)
    for cell in sheet[row_number]:
        cell.fill = SEPARATOR_FILL
