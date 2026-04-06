import io
import sys
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
            patch.object(load_data_module.os.path, "isdir", return_value=True),
            patch("builtins.open", return_value=io.StringIO(GRAPH_TEXT)),
        ):
            load_data_module.load_data()

        self.assertEqual(fake_session.commits, 1)
        self.assertEqual(len(fake_session.added), 1)
        inserted_bug = fake_session.added[0]
        self.assertEqual(inserted_bug.bug_id, 2)
        self.assertEqual(inserted_bug.gui_graph, "filtered-graph")
        self.assertIn(HASH_A, inserted_bug.screen_descriptions)
        self.assertIn(HASH_B, inserted_bug.screen_descriptions)


if __name__ == "__main__":
    unittest.main()
