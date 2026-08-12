import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import report_media


def _turn_record(screen_reference, steps=None):
    """Build a log turn shaped like the one the extraction nodes emit."""
    actions = [
        {
            "entity": "bot",
            "action_name": "extract_and_update",
            "output": {
                "BugInfo": {"triggering_screen_reference": screen_reference},
                "information_element_extraction": {"triggering_screen_reference": None},
            },
        }
    ]

    if steps is not None:
        actions.append(
            {
                "entity": "bot",
                "action_name": "generate_report",
                "output": {"full_report": {"title": "Crash", "steps_to_reproduce": steps}},
            }
        )

    return {"session_id": "session-1", "turn": 1, "actions": actions}


def _candidates(*values):
    return {
        "status": "inferred",
        "candidates": [{"value": value, "evidence": "because"} for value in values],
    }


class ReportMediaTestCase(unittest.TestCase):
    """Point the media resolver at a throwaway dataset, log file and session record."""

    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name)

        # Mirror dataset/graphs_json_data_<DATASET>/Bug7/<app>/{states,transitions}.
        self.app_directory = self.root / "dataset" / "Bug7" / "1-com.example.app-1.0"
        (self.app_directory / "states").mkdir(parents=True)
        (self.app_directory / "transitions").mkdir(parents=True)
        self._write_screenshot("states", "614959519")
        self._write_screenshot("transitions", "990647563")
        self._write_screenshot("transitions", "-993716096")

        self.log_path = self.root / "session-1.log"

        patcher = patch.object(report_media, "SCREENSHOT_ROOT", self.root / "dataset")
        patcher.start()
        self.addCleanup(patcher.stop)

        log_patcher = patch.object(
            report_media, "build_api_log_path", return_value=self.log_path
        )
        log_patcher.start()
        self.addCleanup(log_patcher.stop)

        session_patcher = patch.object(
            report_media, "get_session", return_value={"bug_id": 7, "status": "completed"}
        )
        self.mock_get_session = session_patcher.start()
        self.addCleanup(session_patcher.stop)

    def _write_screenshot(self, kind: str, image_id: str) -> None:
        (self.app_directory / kind / f"{image_id}.png").write_bytes(b"png")

    def _write_log(self, records: list[dict]) -> None:
        self.log_path.write_text(
            "\n".join(json.dumps(record, indent=2) for record in records),
            encoding="utf-8",
        )


class BuildReportMediaTests(ReportMediaTestCase):
    def test_uses_the_latest_non_null_screen_reference(self):
        self._write_log(
            [
                _turn_record(_candidates("614959519")),
                _turn_record(None),
                _turn_record(_candidates("-1415464106")),
                _turn_record(None),
            ]
        )

        media = report_media.build_report_media("session-1")

        self.assertEqual(media.screen_id, "-1415464106")
        self.assertFalse(media.has_screen_screenshot)

    def test_prefers_the_best_supported_candidate_and_reports_its_screenshot(self):
        self._write_log([_turn_record(_candidates("614959519", "739537420"))])

        media = report_media.build_report_media("session-1")

        self.assertEqual(media.screen_id, "614959519")
        self.assertTrue(media.has_screen_screenshot)
        self.assertEqual(media.app_name, "1-com.example.app-1.0")
        self.assertEqual(media.bug_id, 7)

    def test_reads_a_bare_value_screen_reference(self):
        self._write_log([_turn_record({"value": "614959519", "evidence": ["said so"]})])

        self.assertEqual(report_media.build_report_media("session-1").screen_id, "614959519")

    def test_splits_steps_into_text_and_transition_screenshots(self):
        self._write_log(
            [
                _turn_record(
                    _candidates("614959519"),
                    steps=(
                        "1. Open the app. <-707067098>\n"
                        "2. Open the statistics tab. <990647563>\n"
                        "3. Tap Go. <-993716096>"
                    ),
                )
            ]
        )

        steps = report_media.build_report_media("session-1").steps

        self.assertEqual([step.index for step in steps], [1, 2, 3])
        self.assertEqual(steps[1].text, "2. Open the statistics tab.")
        self.assertEqual(steps[1].transition_id, "990647563")
        self.assertTrue(steps[1].has_screenshot)
        # The synthetic "open app" transition was never captured as an image.
        self.assertEqual(steps[0].transition_id, "-707067098")
        self.assertFalse(steps[0].has_screenshot)

    def test_reads_steps_stored_as_a_list(self):
        self._write_log(
            [_turn_record(None, steps=["Open the app. <990647563>", "Tap Go. <-993716096>"])]
        )

        steps = report_media.build_report_media("session-1").steps

        self.assertEqual([step.text for step in steps], ["Open the app.", "Tap Go."])
        self.assertTrue(all(step.has_screenshot for step in steps))

    def test_keeps_steps_that_carry_no_transition_id(self):
        self._write_log([_turn_record(None, steps="1. Open the app.\n2. Tap Go.")])

        steps = report_media.build_report_media("session-1").steps

        self.assertEqual([step.transition_id for step in steps], [None, None])
        self.assertEqual([step.has_screenshot for step in steps], [False, False])

    def test_ignores_a_user_edited_report_that_lost_its_transition_ids(self):
        self._write_log(
            [
                _turn_record(None, steps="1. Open the statistics tab. <990647563>"),
                {
                    "record_type": "modified_report",
                    "session_id": "session-1",
                    "modified_report": {"steps_to_reproduce": "1. Open the statistics tab."},
                },
            ]
        )

        steps = report_media.build_report_media("session-1").steps

        self.assertEqual([step.transition_id for step in steps], ["990647563"])

    def test_reports_no_media_when_the_session_log_is_missing(self):
        media = report_media.build_report_media("session-1")

        self.assertIsNone(media.screen_id)
        self.assertFalse(media.has_screen_screenshot)
        self.assertEqual(media.steps, [])

    def test_rejects_unknown_sessions_and_malformed_session_records(self):
        self.mock_get_session.return_value = None
        with self.assertRaises(report_media.SessionNotFoundError):
            report_media.build_report_media("session-1")

        self.mock_get_session.return_value = {"session_id": "session-1"}
        with self.assertRaises(report_media.InvalidSessionError):
            report_media.build_report_media("session-1")


def _draft_record(revision: int, steps: str) -> dict:
    """Build the terminal draft report record one BURT++ run writes."""
    return {
        "record_type": "draft_report",
        "session_id": "session-1",
        "revision": revision,
        "draft_report": {"title": "Crash", "steps_to_reproduce": steps},
    }


class RegeneratedSessionMediaTests(ReportMediaTestCase):
    """A session regenerated from a saved edit holds one run's media per revision."""

    def setUp(self):
        super().setUp()
        self._write_log(
            [
                _turn_record(_candidates("614959519")),
                _draft_record(1, "1. Open the statistics tab. <990647563>"),
                {
                    "record_type": "modified_report",
                    "session_id": "session-1",
                    "revision": 1,
                    "modified_report": {"title": "Crash on open"},
                },
                _turn_record(_candidates("739537420")),
                _draft_record(2, "1. Tap Go. <-993716096>"),
            ]
        )

    def test_answers_for_the_newest_run_by_default(self):
        media = report_media.build_report_media("session-1")

        self.assertEqual(media.screen_id, "739537420")
        self.assertEqual([step.transition_id for step in media.steps], ["-993716096"])

    def test_answers_for_one_earlier_revision_when_asked(self):
        media = report_media.build_report_media("session-1", revision=1)

        # Only what run 1 had mapped, so the first report card keeps its own screens.
        self.assertEqual(media.screen_id, "614959519")
        self.assertEqual([step.transition_id for step in media.steps], ["990647563"])

    def test_falls_back_to_the_whole_log_for_a_revision_it_cannot_find(self):
        media = report_media.build_report_media("session-1", revision=9)

        self.assertEqual(media.screen_id, "739537420")


class ResolveScreenshotTests(ReportMediaTestCase):
    def test_resolves_a_captured_screenshot(self):
        self.assertEqual(
            report_media.resolve_screenshot("session-1", "states", "614959519"),
            self.app_directory / "states" / "614959519.png",
        )

    def test_returns_none_for_ids_that_were_never_captured(self):
        self.assertIsNone(report_media.resolve_screenshot("session-1", "states", "-707067098"))

    def test_refuses_directory_traversal_and_unknown_kinds(self):
        self.assertIsNone(
            report_media.resolve_screenshot("session-1", "states", "../../../../etc/passwd")
        )
        self.assertIsNone(report_media.resolve_screenshot("session-1", "..", "614959519"))
        self.assertIsNone(report_media.resolve_screenshot("session-1", "states", "614959519/.."))


if __name__ == "__main__":
    unittest.main()
