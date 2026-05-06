import argparse
import csv
from pathlib import Path
from pprint import pprint
from uuid import uuid4

import config
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from .burt import (
    BugAgentState,
    _flush_active_turn,
    build_burt_graph,
    create_runtime_context,
    ingest_user_description,
    load_bug_graph_context,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DESCRIPTION_CSV_PATH = REPO_ROOT / "gt_and_test_data" / f"{config.DATASET}.csv"


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for one BURT runtime invocation."""
    parser = argparse.ArgumentParser(description="Run the BURT bug-report workflow.")
    parser.add_argument(
        "--bug-id",
        type=int,
        required=True,
        help="Bug ID used to fetch the app graph and app name.",
    )
    parser.add_argument(
        "--description-level",
        required=True,
        help="Description level in the format [completeness level]_[precision level].",
    )

    return parser.parse_args()


def normalize_description_level(description_level: str) -> str:
    """Normalize and validate a description-level string such as ``LC_LP``."""
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


def load_initial_message(current_bug: int, description_level: str) -> str:
    """Load the initial user description for one bug and description level."""
    normalized_level = normalize_description_level(description_level)
    description_column = f"{normalized_level} Desc"

    with DESCRIPTION_CSV_PATH.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            if row.get("bug_id") != str(current_bug):
                continue

            initial_message = (row.get(description_column) or "").strip()
            if not initial_message:
                raise ValueError(
                    f"No initial message found for bug ID {current_bug} and description level {normalized_level}."
                )
            return initial_message

    raise ValueError(f"Bug ID {current_bug} was not found in {DESCRIPTION_CSV_PATH}.")


def main() -> None:
    """Run one complete BURT CLI session from input load through log write."""
    args = parse_args()
    initial_message = load_initial_message(
        current_bug=args.bug_id,
        description_level=args.description_level,
    )
    transitions, app_name, screen_descriptions = load_bug_graph_context(
        current_bug=args.bug_id
    )

    session_id = str(uuid4())

    runtime_context = create_runtime_context(
        session_id=session_id,
        log_path=Path("logs") / str(config.PROMPT_VERSION) / f"{session_id}.log",
    )

    runtime_context.logger.filepath.unlink(missing_ok=True)

    graph = build_burt_graph(MemorySaver())
    agent_config = {
        "configurable": {
            "transitions": transitions,
            "app_name": app_name,
            "screen_descriptions": screen_descriptions,
            "thread_id": session_id,
            "runtime_context": runtime_context,
        }
    }
    initial_state_update = ingest_user_description(
        initial_message,
        runtime_context=runtime_context,
    )
    state = BugAgentState(messages=[initial_state_update["messages"]])

    result = graph.invoke(state, config=agent_config)
    _flush_active_turn(runtime_context)

    while True:
        if "__interrupt__" not in result:
            break

        snapshot = graph.get_state(agent_config)
        print("STATE BEFORE NEXT FOLLOW UP:\n")
        pprint(snapshot.values, width=100)
        print("\n\n")

        question = result["__interrupt__"]
        print(question)
        user_response = input("> ")

        result = graph.invoke(Command(resume=user_response), config=agent_config)
        _flush_active_turn(runtime_context)

    print("FINAL BUG REPORT:\n\n")
    final_report = result["full_report"]
    print(final_report)
    runtime_context.sink.finalize_session(
        session_id=runtime_context.session_id,
        final_report=final_report,
        run_metadata={
            "bug_id": args.bug_id,
            "description_level": args.description_level,
            "input_source": config.DATASET,
            "runtime": "cli",
        },
    )


if __name__ == "__main__":
    main()
