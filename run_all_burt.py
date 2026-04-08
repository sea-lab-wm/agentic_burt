import argparse
import ast
import csv
import subprocess
import sys
from pathlib import Path

import config


DESCRIPTION_SUFFIX = " Desc"
BURT_SCRIPT_PATH = Path("burt.py")
DESCRIPTION_CSV_PATH = Path(config.DESCRIPTION_CSV_PATH)
LOGS_ROOT = Path("logs")


def extract_description_levels(fieldnames: list[str]) -> list[str]:
    return [
        fieldname.removesuffix(DESCRIPTION_SUFFIX)
        for fieldname in fieldnames
        if fieldname.endswith(DESCRIPTION_SUFFIX)
    ]


def load_runs(csv_path: Path) -> list[tuple[int, str]]:
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        description_levels = extract_description_levels(fieldnames)

        if not description_levels:
            raise ValueError(f"No description-level columns ending in '{DESCRIPTION_SUFFIX}' were found in {csv_path}.")

        runs: list[tuple[int, str]] = []
        for row in reader:
            bug_id_value = (row.get("bug_id") or "").strip()
            if not bug_id_value:
                continue

            bug_id = int(bug_id_value)
            for description_level in description_levels:
                description_column = f"{description_level}{DESCRIPTION_SUFFIX}"
                if (row.get(description_column) or "").strip():
                    runs.append((bug_id, description_level))

    return runs


def normalize_description_level(description_level: str) -> str:
    normalized = description_level.strip().upper().replace("-", "_")
    try:
        completeness_level, precision_level = normalized.split("_", maxsplit=1)
    except ValueError as exc:
        raise ValueError(
            "Description level must use the format [L|M|H]C_[L|M|H]P, for example LC_MP."
        ) from exc

    if len(completeness_level) != 2 or completeness_level[1] != "C":
        raise ValueError("Completeness level must be one of LC, MC, HC.")
    if len(precision_level) != 2 or precision_level[1] != "P":
        raise ValueError("Precision level must be one of LP, MP, HP.")

    if completeness_level[0] not in {"L", "M", "H"} or precision_level[0] not in {"L", "M", "H"}:
        raise ValueError("Description level must use only L, M, or H prefixes.")

    return f"{completeness_level}_{precision_level}"


def parse_limit_desc_to(raw_value: str) -> list[tuple[int, str]]:
    try:
        parsed = ast.literal_eval(raw_value)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(
            "--limit-desc-to must be a Python-style list of (bug_id, description_level) tuples."
        ) from exc

    if not isinstance(parsed, list):
        raise ValueError("--limit-desc-to must evaluate to a list.")

    normalized_pairs: list[tuple[int, str]] = []
    for entry in parsed:
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise ValueError(
                "--limit-desc-to entries must be 2-item tuples like (10, 'LC_LP')."
            )

        bug_id_raw, description_level_raw = entry
        if not isinstance(bug_id_raw, int):
            raise ValueError("Each --limit-desc-to bug_id must be an integer.")
        if not isinstance(description_level_raw, str):
            raise ValueError("Each --limit-desc-to description level must be a string.")

        normalized_pairs.append((bug_id_raw, normalize_description_level(description_level_raw)))

    return normalized_pairs


def filter_runs(
    runs: list[tuple[int, str]],
    limit_pairs: list[tuple[int, str]] | None,
) -> list[tuple[int, str]]:
    if limit_pairs is None:
        return runs

    runnable_pairs = set(runs)
    requested_pairs = set(limit_pairs)
    missing_pairs = sorted(requested_pairs - runnable_pairs)
    if missing_pairs:
        formatted_pairs = ", ".join(f"({bug_id}, {description_level})" for bug_id, description_level in missing_pairs)
        raise ValueError(
            "Requested --limit-desc-to pairs are not runnable from the description CSV: "
            f"{formatted_pairs}"
        )

    return [run for run in runs if run in requested_pairs]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BURT across all runnable bug/description pairs.")
    parser.add_argument(
        "--limit-desc-to",
        help='Optional Python-style list of (bug_id, description_level) tuples, e.g. "[(10, \'LC_LP\')]".',
    )
    return parser.parse_args()


def run_burt(python_executable: str, bug_id: int, description_level: str) -> int:
    command = [
        python_executable,
        str(BURT_SCRIPT_PATH),
        "--bug-id",
        str(bug_id),
        "--description-level",
        description_level,
    ]
    print(f"\n=== Running bug {bug_id} at {description_level} ===", flush=True)
    completed = subprocess.run(command, check=False)
    return completed.returncode


def run_evaluator(python_executable: str) -> int:
    log_dir = LOGS_ROOT / str(config.PROMPT_VERSION)
    command = [
        python_executable,
        "-m",
        "evaluator.runner",
        str(log_dir),
    ]
    print(f"\n=== Evaluating logs in {log_dir} ===", flush=True)
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main() -> int:
    args = parse_args()
    csv_path = DESCRIPTION_CSV_PATH

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV path does not exist: {csv_path}")

    runs = load_runs(csv_path)
    limit_pairs = parse_limit_desc_to(args.limit_desc_to) if args.limit_desc_to else None
    runs = filter_runs(runs, limit_pairs)
    if not runs:
        raise ValueError(f"No runnable bug/description-level pairs were found in {csv_path}.")

    failures: list[tuple[int, str, int]] = []
    for bug_id, description_level in runs:
        return_code = run_burt(sys.executable, bug_id, description_level)
        if return_code != 0:
            failures.append((bug_id, description_level, return_code))

    evaluator_return_code = run_evaluator(sys.executable)

    print("\n=== Batch Summary ===")
    print(f"Total runs: {len(runs)}")
    print(f"Failures: {len(failures)}")
    print(f"Evaluator exit code: {evaluator_return_code}")

    if failures:
        for bug_id, description_level, return_code in failures:
            print(f"bug {bug_id} at {description_level}: exit code {return_code}")
    if evaluator_return_code != 0:
        print(f"evaluator.runner on logs/{config.PROMPT_VERSION}: exit code {evaluator_return_code}")

    if failures or evaluator_return_code != 0:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
