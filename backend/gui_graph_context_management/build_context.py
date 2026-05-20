"""Utilities for building GUI graph context JSON files on disk."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# from backend import config

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config

try:
    from .generate_screen_descriptions import generate_screen_descriptions
    from .graph_data_parser import filter_graph, get_graph_file_path
except ImportError:  # pragma: no cover - support direct script execution
    from generate_screen_descriptions import generate_screen_descriptions
    from graph_data_parser import filter_graph, get_graph_file_path

OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "json_graph_data" / config.DATASET
GRAPH_DATA_DIR = f"backend/dataset/graphs_json_data_{config.DATASET}"


if config.DATASET == "BugScribe_dev":
    SELECTED_DATA = {
        2: "Family_Finance",
        10: "Material_Files",
        110: "Vinyl_Music_Player",
        117: "Open_Food_Facts_Food_Scanner",
        130: "andOTP_OTP_Authenticator",
        135: "Wikimedia_Commons",
        248: "ODK_Collect",
        1299: "Field_Book",
        1563: "lrkFM_File_Manager",
        1568: "lrkFM_File_Manager",
    }
elif config.DATASET == "BugScribe_Test":
    pass
elif config.DATASET == "BURT":
    SELECTED_DATA = {
        1: "APOD",
        2: "APOD",
        3: "GNU",
        4: "GNU",
        5: "GROW",
        6: "GROW",
        7: "TIME",
        8: "TIME",
        9: "TOKEN",
        10: "TOKEN",
        11: "DROID",
        12: "DROID",
    }


# def _split_text_block_into_lines(text: str) -> list[str]:
#     """Return a stable JSON-friendly representation for a text block."""
#     stripped = text.strip()
#     if not stripped:
#         return []
#     return stripped.splitlines()


def _split_text_block_into_lines(text: str) -> list[str]:
    """Return non-empty stripped lines for JSON serialization."""

    stripped = text.strip()

    if not stripped:
        return []

    return [
        line.strip()
        for line in stripped.splitlines()
        if line.strip()
    ]


def _resolve_output_path(bug_id: int) -> Path:
    """Return the output path for one bug context payload."""
    return OUTPUT_ROOT / f"bug{bug_id}" / "context.json"


def _build_context_payload(
    app_name: str,
    transitions_text: str,
    screen_descriptions_text: str,
) -> dict[str, object]:
    """Build the persisted JSON payload for one bug."""
    return {
        "application_name": app_name,
        "transitions": _split_text_block_into_lines(transitions_text),
        "screen_names_and_descriptions": _split_text_block_into_lines(
            screen_descriptions_text
        ),
    }


def _write_context_payload(output_path: Path, payload: dict[str, object]) -> None:
    """Persist one bug context payload as formatted JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(payload, output_file, indent=2, ensure_ascii=False, sort_keys=True)
        output_file.write("\n")


# def _get_data_dir(mode: str) -> str:
#     """Resolve the raw graph dataset location for the requested mode."""
#     if mode == "dev":
#         return GRAPH_DATA_DIR
#     if mode == "test":
#         return TEST_DATA_DIR
#     raise ValueError("Please set mode to either 'dev' or 'test")


def build_context() -> None:
    """Build GUI graph context JSON files for the selected bug set."""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(env_path)

    screen_description_model = ChatOpenAI(model="gpt-5.4")
    # data_dir = _get_data_dir(mode)
    data_dir = GRAPH_DATA_DIR

    print("Walking Bug Reports")
    if not os.path.isdir(data_dir):
        raise FileNotFoundError(
            f"DATA_DIR does not exist or is not a directory: {data_dir}"
        )

    for bug_num, app_name in SELECTED_DATA.items():
        try:
            graph_file_path = get_graph_file_path(data_dir, bug_num)
        except FileNotFoundError as exc:
            print(f"Skipping Bug{bug_num}: {exc}")
            continue

        with open(graph_file_path, "r", encoding="utf-8") as graph_file:
            unfiltered_graph_text = graph_file.read()
            filtered_graph_text = filter_graph(
                unfiltered_graph_text=unfiltered_graph_text
            )

        screen_descriptions = generate_screen_descriptions(
            unfiltered_graph_text,
            screen_description_model,
        )
        print(f"generated bug descriptions for bug {bug_num}")

        payload = _build_context_payload(
            app_name=app_name,
            transitions_text=filtered_graph_text,
            screen_descriptions_text=screen_descriptions,
        )
        output_path = _resolve_output_path(bug_num)
        _write_context_payload(output_path, payload)
        print(
            f"Wrote GUI graph context for bug {bug_num} to {output_path} "
            f"(transition lines: {len(payload['transitions'])} "
            f"screen description lines: {len(payload['screen_names_and_descriptions'])})"
        )


if __name__ == "__main__":
    build_context()
