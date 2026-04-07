from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

import config
from evaluator.generate_review import (
    RESULTS_ROOT,
    rebuild_manual_review_workbook,
)
from evaluator.judges import (
    InfoElementsJudgeResult,
    S2RJudgeResult,
    extract_information_elements_from_OB_EB,
    judge_information_elements,
    judge_s2r,
)
from evaluator.parsing import build_log_context, discover_log_paths, load_ground_truth_rows


def parse_args() -> argparse.Namespace:
    """Parse evaluator CLI arguments."""
    parser = argparse.ArgumentParser(description="Evaluate BURT logs with LLM-as-judge prompts.")
    parser.add_argument("paths", nargs="+", help="One or more log files or directories.")
    parser.add_argument(
        "--model",
        default=config.MODEL_NAME,
        help=f"Judge model name. Defaults to {config.MODEL_NAME}.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the full evaluator pipeline for the requested log inputs."""
    load_dotenv()
    args = parse_args()

    log_paths = discover_log_paths(args.paths)
    if not log_paths:
        raise SystemExit("No log files were found for the provided inputs.")

    ground_truth_rows = load_ground_truth_rows()
    model = ChatOpenAI(model=args.model)

    results_by_version: dict[str, list[Path]] = {}
    for log_path in log_paths:
        # Each log is evaluated independently and persisted immediately so a
        # partial run still leaves behind useful artifacts.
        result = evaluate_log(log_path=log_path, model=model, ground_truth_rows=ground_truth_rows)
        output_path = write_evaluation_result(result)
        results_by_version.setdefault(result["agent_version"], []).append(output_path)

    for agent_version in results_by_version:
        rebuild_manual_review_workbook(agent_version)


def evaluate_log(log_path: Path, model: Any, ground_truth_rows: dict[int, dict[str, str]]) -> dict[str, Any]:
    """Evaluate one parsed BURT log and return the persisted JSON payload."""
    context = build_log_context(log_path, ground_truth_rows)
    timestamp = datetime.now(timezone.utc).isoformat()

    result: dict[str, Any] = {
        "log_path": context["log_path"],
        "bug_id": context["bug_id"],
        "description_level": context["description_level"],
        "agent_version": context["agent_version"],
        "app_name": context.get("app_name"),
        "title": (context.get("full_report") or {}).get("title"),
        "full_report": context.get("full_report"),
        "ground_truth": context.get("ground_truth"),
        "recomputed_info_elements": None,
        "info_elements_judge": None,
        "s2r_judge": None,
        "judge_model": getattr(model, "model_name", None) or getattr(model, "model", None),
        "evaluated_at": timestamp,
        "status": "ok",
        "error": None,
        "parse_status": context["parse_status"],
        "parse_error": context["parse_error"],
    }

    if context["parse_status"] != "ok":
        # Parsing failures are written as result artifacts instead of raising so
        # multi-log runs can continue and the failure remains inspectable.
        result["status"] = "parse_error"
        return result

    full_report = context["full_report"] or {}
    ground_truth = context.get("ground_truth") or {}

    info_judge_result: InfoElementsJudgeResult | None = None
    s2r_judge_result: S2RJudgeResult | None = None

    try:
        # Recompute the information elements from the final report so judging is
        # based on a fresh extraction pass, not only the values captured in the log.
        result["recomputed_info_elements"] = extract_information_elements_from_OB_EB(
            observed_behavior=full_report.get("observed_behavior", ""),
            expected_behavior=full_report.get("expected_behavior", ""),
            model=model,
        )
    except Exception as exc:
        result["status"] = "judge_error"
        result["error"] = f"Failed to recompute info elements: {exc}"

    if result["recomputed_info_elements"] and ground_truth.get("info_elements_gt"):
        try:
            info_judge_result = judge_information_elements(
                generated_info_elements=result["recomputed_info_elements"],
                ground_truth_info_elements=ground_truth["info_elements_gt"],
                model=model,
            )
            result["info_elements_judge"] = info_judge_result.model_dump()
        except Exception as exc:
            result["status"] = "judge_error"
            result["error"] = _append_error(result["error"], f"Information-elements judge failed: {exc}")
    else:
        result["info_elements_judge"] = {
            "status": "skipped",
            "reason": "Missing recomputed info elements or info_elements_gt.",
        }

    if full_report.get("steps_to_reproduce") and ground_truth.get("S2R_ground_truth"):
        try:
            s2r_judge_result = judge_s2r(
                generated_s2rs=full_report["steps_to_reproduce"],
                ground_truth_s2r=ground_truth["S2R_ground_truth"],
                model=model,
            )
            result["s2r_judge"] = [step.model_dump() for step in s2r_judge_result.steps]
        except Exception as exc:
            result["status"] = "judge_error"
            result["error"] = _append_error(result["error"], f"S2R judge failed: {exc}")
    else:
        result["s2r_judge"] = {
            "status": "skipped",
            "reason": "Missing generated S2R or S2R_ground_truth.",
        }

    return result


def write_evaluation_result(result: dict[str, Any]) -> Path:
    """Write one evaluation JSON under Results/<agent_version>/."""
    version_dir = RESULTS_ROOT / result["agent_version"]
    version_dir.mkdir(parents=True, exist_ok=True)
    output_path = version_dir / f"{Path(result['log_path']).stem}.evaluation.json"
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return output_path


def _append_error(existing_error: str | None, new_error: str) -> str:
    """Accumulate multiple evaluator errors into one readable field."""
    if not existing_error:
        return new_error
    return f"{existing_error} | {new_error}"


if __name__ == "__main__":
    main()
