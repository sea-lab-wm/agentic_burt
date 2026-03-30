import csv
import subprocess
import sys
from pathlib import Path

import config


DESCRIPTION_SUFFIX = " Desc"
BURT_SCRIPT_PATH = Path("burt.py")
DESCRIPTION_CSV_PATH = Path(config.DESCRIPTION_CSV_PATH)


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


def run_burt(python_executable: str, bug_id: int, description_level: str) -> int:
    command = [
        python_executable,
        str(BURT_SCRIPT_PATH),
        "--current-bug-id",
        str(bug_id),
        "--description-level",
        description_level,
    ]
    print(f"\n=== Running bug {bug_id} at {description_level} ===", flush=True)
    completed = subprocess.run(command, check=False)
    return completed.returncode


def main() -> int:
    csv_path = DESCRIPTION_CSV_PATH

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV path does not exist: {csv_path}")

    runs = load_runs(csv_path)
    if not runs:
        raise ValueError(f"No runnable bug/description-level pairs were found in {csv_path}.")

    failures: list[tuple[int, str, int]] = []
    for bug_id, description_level in runs:
        return_code = run_burt(sys.executable, bug_id, description_level)
        if return_code != 0:
            failures.append((bug_id, description_level, return_code))

    print("\n=== Batch Summary ===")
    print(f"Total runs: {len(runs)}")
    print(f"Failures: {len(failures)}")

    if failures:
        for bug_id, description_level, return_code in failures:
            print(f"bug {bug_id} at {description_level}: exit code {return_code}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
