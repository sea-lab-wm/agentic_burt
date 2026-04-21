import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(0, str(DATABASE_DIR))

from database.generate_screen_descriptions import generate_screen_descriptions
from database.generate_screen_descriptions import ScreenDescriptionItem, ScreenDescriptionsOutput
from database.graph_data_parser import get_screens_with_information_from_text
from database import load_data as load_data_module
from gui_graph_context_access import build_context as build_context_module


HASH_A = "a" * 64
HASH_B = "b" * 64
TRANSITION_HASH = "c" * 64
GRAPH_TEXT = f"""Transitions (1):
{TRANSITION_HASH}: (s:{HASH_A}, t:{HASH_B}): [act=(0) click]
States (2):
{HASH_A}, HomeScreen, activity=HomeActivity
  component: button=Continue
{HASH_B}, SettingsScreen, activity=SettingsActivity
  component: toggle=Enable notifications
"""


class FakeModel:
    def __init__(self, response):
        self.response = response
        self.prompts = []
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, messages):
        self.prompts.append(messages)
        return self.response


class FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1


class ScreenDescriptionTests(unittest.TestCase):
    def test_get_screens_with_information_from_text_returns_ordered_blocks_and_maps(self):
        screens, screen_id_map, reverse_screen_id_map = get_screens_with_information_from_text(GRAPH_TEXT)

        self.assertEqual(len(screens), 2)
        self.assertTrue(screens[0].startswith("S1"))
        self.assertTrue(screens[1].startswith("S2"))
        self.assertEqual(screen_id_map["S1"], HASH_A)
        self.assertEqual(screen_id_map["S2"], HASH_B)
        self.assertEqual(reverse_screen_id_map[HASH_A], "S1")
        self.assertEqual(reverse_screen_id_map[HASH_B], "S2")

    def test_get_screens_with_information_from_text_handles_missing_states(self):
        screens, screen_id_map, reverse_screen_id_map = get_screens_with_information_from_text("Transitions (0):\n")

        self.assertEqual(screens, [])
        self.assertEqual(screen_id_map, {})
        self.assertEqual(reverse_screen_id_map, {})

    def test_generate_screen_descriptions_restores_original_screen_ids(self):
        model = FakeModel(
            ScreenDescriptionsOutput(
                screen_descriptions=[
                    ScreenDescriptionItem(
                        screen_id="S1",
                        screen_name="HomeScreen",
                        short_description="Landing page.",
                    ),
                    ScreenDescriptionItem(
                        screen_id="S2",
                        screen_name="SettingsScreen",
                        short_description="Settings page.",
                    ),
                ]
            )
        )

        result = generate_screen_descriptions(GRAPH_TEXT, model)

        self.assertIn(HASH_A, result)
        self.assertIn(HASH_B, result)
        self.assertNotIn("S1 -", result)
        self.assertNotIn("S2 -", result)
        self.assertEqual(len(model.prompts), 1)
        self.assertIs(model.schema, ScreenDescriptionsOutput)
        prompt = model.prompts[0][0].content
        self.assertIn("S1", prompt)
        self.assertIn("S2", prompt)
        self.assertIn("HomeScreen", prompt)
        self.assertIn("SettingsScreen", prompt)

    def test_load_data_populates_bug_screen_descriptions(self):
        fake_model = FakeModel(
            ScreenDescriptionsOutput(
                screen_descriptions=[
                    ScreenDescriptionItem(
                        screen_id="S1",
                        screen_name="HomeScreen",
                        short_description="Landing page.",
                    ),
                    ScreenDescriptionItem(
                        screen_id="S2",
                        screen_name="SettingsScreen",
                        short_description="Settings page.",
                    ),
                ]
            )
        )
        fake_session = FakeSession()

        with (
            patch.object(load_data_module, "SELECTED_DATA", {2: "Family_Finance"}),
            patch.object(load_data_module, "db_session", fake_session),
            patch.object(load_data_module, "ChatOpenAI", return_value=fake_model),
            patch.object(load_data_module, "get_graph_file_path", return_value="/tmp/Bug2/graph.txt"),
            patch.object(load_data_module, "filter_graph", return_value="filtered-graph"),
            patch.object(load_data_module, "load_dotenv"),
            patch.object(load_data_module.os.path, "isdir", return_value=True),
            patch("builtins.open", side_effect=lambda *args, **kwargs: io.StringIO(GRAPH_TEXT)),
        ):
            load_data_module.load_data()

        self.assertEqual(fake_session.commits, 1)
        self.assertEqual(len(fake_session.added), 1)
        inserted_bug = fake_session.added[0]
        self.assertEqual(inserted_bug.bug_id, 2)
        self.assertEqual(inserted_bug.gui_graph, "filtered-graph")
        self.assertIn(HASH_A, inserted_bug.screen_descriptions)
        self.assertIn(HASH_B, inserted_bug.screen_descriptions)

    def test_build_context_writes_json_graph_context(self):
        fake_model = FakeModel(
            ScreenDescriptionsOutput(
                screen_descriptions=[
                    ScreenDescriptionItem(
                        screen_id="S1",
                        screen_name="HomeScreen",
                        short_description="Landing page.",
                    ),
                    ScreenDescriptionItem(
                        screen_id="S2",
                        screen_name="SettingsScreen",
                        short_description="Settings page.",
                    ),
                ]
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "gui_graph_context"

            with (
                patch.object(build_context_module, "SELECTED_DATA", {2: "Family_Finance"}),
                patch.object(build_context_module, "OUTPUT_ROOT", output_root),
                patch.object(build_context_module, "ChatOpenAI", return_value=fake_model),
                patch.object(build_context_module, "get_graph_file_path", return_value="/tmp/Bug2/graph.txt"),
                patch.object(build_context_module, "filter_graph", return_value="Transitions (1):\nfiltered-graph"),
                patch.object(build_context_module, "load_dotenv"),
                patch.object(build_context_module.os.path, "isdir", return_value=True),
                patch("builtins.open", side_effect=lambda *args, **kwargs: io.StringIO(GRAPH_TEXT)),
            ):
                build_context_module.build_context()

            output_path = output_root / "bug2" / "context.json"
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["application_name"], "Family_Finance")
        self.assertEqual(payload["transitions"], ["Transitions (1):", "filtered-graph"])
        self.assertEqual(
            payload["screen_names_and_descriptions"],
            [
                f"{HASH_A} - HomeScreen: Landing page.",
                f"{HASH_B} - SettingsScreen: Settings page.",
            ],
        )
        self.assertNotIn("S1 -", "\n".join(payload["screen_names_and_descriptions"]))
        self.assertNotIn("S2 -", "\n".join(payload["screen_names_and_descriptions"]))

    def test_build_context_uses_empty_array_for_blank_screen_descriptions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "gui_graph_context"

            with (
                patch.object(build_context_module, "SELECTED_DATA", {2: "Family_Finance"}),
                patch.object(build_context_module, "OUTPUT_ROOT", output_root),
                patch.object(build_context_module, "ChatOpenAI", return_value=object()),
                patch.object(build_context_module, "get_graph_file_path", return_value="/tmp/Bug2/graph.txt"),
                patch.object(build_context_module, "filter_graph", return_value="filtered-graph"),
                patch.object(build_context_module, "generate_screen_descriptions", return_value=""),
                patch.object(build_context_module, "load_dotenv"),
                patch.object(build_context_module.os.path, "isdir", return_value=True),
                patch("builtins.open", side_effect=lambda *args, **kwargs: io.StringIO(GRAPH_TEXT)),
            ):
                build_context_module.build_context()

            payload = json.loads(
                (output_root / "bug2" / "context.json").read_text(encoding="utf-8")
            )

        self.assertEqual(payload["screen_names_and_descriptions"], [])

    def test_build_context_skips_missing_bug_folder_and_continues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "gui_graph_context"

            def fake_get_graph_file_path(_data_dir, bug_id):
                if bug_id == 2:
                    raise FileNotFoundError("missing bug graph")
                return "/tmp/Bug10/graph.txt"

            with (
                patch.object(
                    build_context_module,
                    "SELECTED_DATA",
                    {2: "Family_Finance", 10: "Material_Files"},
                ),
                patch.object(build_context_module, "OUTPUT_ROOT", output_root),
                patch.object(build_context_module, "ChatOpenAI", return_value=object()),
                patch.object(build_context_module, "get_graph_file_path", side_effect=fake_get_graph_file_path),
                patch.object(build_context_module, "filter_graph", return_value="filtered-graph"),
                patch.object(build_context_module, "generate_screen_descriptions", return_value="screen line"),
                patch.object(build_context_module, "load_dotenv"),
                patch.object(build_context_module.os.path, "isdir", return_value=True),
                patch("builtins.open", side_effect=lambda *args, **kwargs: io.StringIO(GRAPH_TEXT)),
            ):
                build_context_module.build_context()

            self.assertFalse((output_root / "bug2" / "context.json").exists())
            self.assertTrue((output_root / "bug10" / "context.json").exists())

    def test_build_context_raises_for_missing_data_root(self):
        with (
            patch.object(build_context_module, "load_dotenv"),
            patch.object(build_context_module, "ChatOpenAI", return_value=object()),
            patch.object(build_context_module.os.path, "isdir", return_value=False),
        ):
            with self.assertRaisesRegex(
                FileNotFoundError,
                "DATA_DIR does not exist or is not a directory",
            ):
                build_context_module.build_context()

    def test_build_context_rejects_invalid_mode(self):
        with (
            patch.object(build_context_module, "load_dotenv"),
            patch.object(build_context_module, "ChatOpenAI", return_value=object()),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Please set mode to either 'dev' or 'test",
            ):
                build_context_module.build_context(mode="invalid")

    def test_build_context_overwrites_existing_output_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir) / "gui_graph_context"
            output_path = output_root / "bug2" / "context.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text('{"stale": true}\n', encoding="utf-8")

            with (
                patch.object(build_context_module, "SELECTED_DATA", {2: "Family_Finance"}),
                patch.object(build_context_module, "OUTPUT_ROOT", output_root),
                patch.object(build_context_module, "ChatOpenAI", return_value=object()),
                patch.object(build_context_module, "get_graph_file_path", return_value="/tmp/Bug2/graph.txt"),
                patch.object(build_context_module, "filter_graph", return_value="new-graph"),
                patch.object(build_context_module, "generate_screen_descriptions", return_value="new-screen"),
                patch.object(build_context_module, "load_dotenv"),
                patch.object(build_context_module.os.path, "isdir", return_value=True),
                patch("builtins.open", side_effect=lambda *args, **kwargs: io.StringIO(GRAPH_TEXT)),
            ):
                build_context_module.build_context()

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["application_name"], "Family_Finance")
        self.assertEqual(payload["transitions"], ["new-graph"])
        self.assertEqual(payload["screen_names_and_descriptions"], ["new-screen"])


if __name__ == "__main__":
    unittest.main()
