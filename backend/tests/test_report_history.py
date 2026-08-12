import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import report_history


def _draft(revision, title):
    return {
        "record_type": "draft_report",
        "session_id": "session-1",
        "revision": revision,
        "draft_report": {"title": title},
    }


def _final(revision, title):
    return {
        "record_type": "modified_report",
        "session_id": "session-1",
        "revision": revision,
        "modified_report": {"title": title},
    }


class ReportHistoryTestCase(unittest.TestCase):
    """Point the history reader at a throwaway log file and session record."""

    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.log_path = Path(self._temporary_directory.name) / "session-1.log"
        self.log_path.write_text("", encoding="utf-8")

        log_patcher = patch.object(
            report_history, "build_api_log_path", return_value=self.log_path
        )
        log_patcher.start()
        self.addCleanup(log_patcher.stop)

        session_patcher = patch.object(
            report_history,
            "get_session",
            return_value={"bug_id": 7, "status": "completed"},
        )
        self.mock_get_session = session_patcher.start()
        self.addCleanup(session_patcher.stop)

    def _write_log(self, records):
        self.log_path.write_text(
            "\n".join(json.dumps(record, indent=2) for record in records),
            encoding="utf-8",
        )


class BuildSessionReportsTests(ReportHistoryTestCase):
    def test_replays_drafts_and_saved_edits_in_the_order_they_were_written(self):
        self._write_log(
            [
                {"session_id": "session-1", "turn": 1, "actions": []},
                _draft(1, "Crash on save"),
                _final(1, "Crash when saving a note"),
                {"session_id": "session-1", "turn": 1, "actions": []},
                _draft(2, "Crash when saving a note"),
            ]
        )

        reports = report_history.build_session_reports("session-1")

        self.assertEqual(
            [(entry.kind, entry.label) for entry in reports.reports],
            [
                ("draft", "Draft report 1"),
                ("final", "Final report 1"),
                ("draft", "Draft report 2"),
            ],
        )
        self.assertEqual(reports.reports[-1].report, {"title": "Crash when saving a note"})
        self.assertEqual(reports.draft_revision, 2)
        self.assertEqual(reports.final_revision, 1)
        self.assertEqual(reports.edits_remaining, 2)
        self.assertEqual(reports.bug_id, 7)

    def test_numbers_pre_revision_records_by_the_order_they_appear(self):
        # Logs written before reports carried a revision still replay in order.
        self._write_log(
            [
                {
                    "record_type": "draft_report",
                    "session_id": "session-1",
                    "draft_report": {"title": "Crash on save"},
                },
                {
                    "record_type": "modified_report",
                    "session_id": "session-1",
                    "modified_report": {"title": "Edited"},
                },
            ]
        )

        reports = report_history.build_session_reports("session-1")

        self.assertEqual(
            [entry.label for entry in reports.reports],
            ["Draft report 1", "Final report 1"],
        )

    def test_counts_an_edit_the_log_has_not_caught_up_with_yet(self):
        # save_modified_report banks the round in Redis before the rerun finishes.
        self._write_log([_draft(1, "Crash on save")])
        self.mock_get_session.return_value = {
            "bug_id": 7,
            "status": "completed",
            "draft_revision": 1,
            "final_revision": 3,
        }

        reports = report_history.build_session_reports("session-1")

        self.assertEqual(reports.final_revision, 3)
        self.assertEqual(reports.edits_remaining, 0)

    def test_reports_an_empty_history_for_a_session_with_no_log_yet(self):
        reports = report_history.build_session_reports("session-1")

        self.assertEqual(reports.reports, [])
        self.assertEqual(reports.draft_revision, 0)
        self.assertEqual(reports.edits_remaining, 3)

    def test_rejects_unknown_sessions_and_malformed_session_records(self):
        self.mock_get_session.return_value = None
        with self.assertRaises(report_history.SessionNotFoundError):
            report_history.build_session_reports("session-1")

        self.mock_get_session.return_value = {"session_id": "session-1"}
        with self.assertRaises(report_history.InvalidSessionError):
            report_history.build_session_reports("session-1")


if __name__ == "__main__":
    unittest.main()
