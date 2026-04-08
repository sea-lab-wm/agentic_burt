import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_all_burt


class RunAllBurtTests(unittest.TestCase):
    def _write_csv(self, content: str) -> Path:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        csv_path = Path(tempdir.name) / "runs.csv"
        csv_path.write_text(content, encoding="utf-8")
        return csv_path

    def test_load_runs_discovers_all_populated_description_pairs(self):
        csv_path = self._write_csv(
            "\n".join(
                [
                    "bug_id,LC_LP Desc,MC_MP Desc,HC_HP Desc",
                    "10,low desc,mid desc,",
                    "20,,,high desc",
                ]
            )
        )

        runs = run_all_burt.load_runs(csv_path)

        self.assertEqual(runs, [(10, "LC_LP"), (10, "MC_MP"), (20, "HC_HP")])

    def test_parse_limit_desc_to_normalizes_description_levels(self):
        parsed = run_all_burt.parse_limit_desc_to("[(10, 'lc-lp'), (12, 'HC_hp')]")

        self.assertEqual(parsed, [(10, "LC_LP"), (12, "HC_HP")])

    def test_parse_limit_desc_to_rejects_malformed_literal(self):
        with self.assertRaisesRegex(ValueError, "Python-style list"):
            run_all_burt.parse_limit_desc_to("not a list")

    def test_parse_limit_desc_to_rejects_invalid_tuple_shape(self):
        with self.assertRaisesRegex(ValueError, "2-item tuples"):
            run_all_burt.parse_limit_desc_to("[(10, 'LC_LP', 'extra')]")

    def test_filter_runs_rejects_pairs_not_in_csv(self):
        runs = [(10, "LC_LP"), (20, "HC_HP")]

        with self.assertRaisesRegex(ValueError, "not runnable"):
            run_all_burt.filter_runs(runs, [(10, "LC_LP"), (30, "MC_MP")])

    def test_run_burt_uses_bug_id_flag(self):
        with patch("run_all_burt.subprocess.run", return_value=SimpleNamespace(returncode=0)) as mock_run:
            return_code = run_all_burt.run_burt("python", 10, "LC_LP")

        self.assertEqual(return_code, 0)
        mock_run.assert_called_once_with(
            ["python", "burt.py", "--bug-id", "10", "--description-level", "LC_LP"],
            check=False,
        )

    @patch("run_all_burt.run_evaluator", return_value=0)
    @patch("run_all_burt.run_burt", side_effect=[0, 0])
    @patch("run_all_burt.load_runs", return_value=[(10, "LC_LP"), (12, "HC_HP")])
    @patch("run_all_burt.parse_args", return_value=SimpleNamespace(limit_desc_to="[(10, 'lc-lp')]"))
    @patch("run_all_burt.DESCRIPTION_CSV_PATH", Path(__file__))
    def test_main_filters_runs_from_limit_desc_to(
        self,
        _mock_args,
        _mock_load_runs,
        mock_run_burt,
        mock_run_evaluator,
    ):
        exit_code = run_all_burt.main()

        self.assertEqual(exit_code, 0)
        mock_run_burt.assert_called_once_with(run_all_burt.sys.executable, 10, "LC_LP")
        mock_run_evaluator.assert_called_once_with(run_all_burt.sys.executable)

    @patch("run_all_burt.parse_args", return_value=SimpleNamespace(limit_desc_to=None))
    @patch("run_all_burt.load_runs", return_value=[(10, "LC_LP"), (12, "HC_HP")])
    @patch("run_all_burt.run_burt", side_effect=[1, 0])
    @patch("run_all_burt.run_evaluator", return_value=0)
    @patch("run_all_burt.DESCRIPTION_CSV_PATH", Path(__file__))
    def test_main_still_runs_evaluator_after_partial_burt_failures(
        self,
        mock_run_evaluator,
        mock_run_burt,
        _mock_load_runs,
        _mock_args,
    ):
        exit_code = run_all_burt.main()

        self.assertEqual(exit_code, 1)
        self.assertEqual(mock_run_burt.call_count, 2)
        mock_run_evaluator.assert_called_once_with(run_all_burt.sys.executable)

    @patch("run_all_burt.parse_args", return_value=SimpleNamespace(limit_desc_to=None))
    @patch("run_all_burt.load_runs", return_value=[(10, "LC_LP")])
    @patch("run_all_burt.run_burt", return_value=0)
    @patch("run_all_burt.run_evaluator", return_value=2)
    @patch("run_all_burt.DESCRIPTION_CSV_PATH", Path(__file__))
    def test_main_returns_nonzero_when_evaluator_fails(
        self,
        mock_run_evaluator,
        mock_run_burt,
        _mock_load_runs,
        _mock_args,
    ):
        exit_code = run_all_burt.main()

        self.assertEqual(exit_code, 1)
        mock_run_burt.assert_called_once_with(run_all_burt.sys.executable, 10, "LC_LP")
        mock_run_evaluator.assert_called_once_with(run_all_burt.sys.executable)

    def test_run_evaluator_targets_prompt_version_log_directory(self):
        with patch("run_all_burt.subprocess.run", return_value=SimpleNamespace(returncode=0)) as mock_run, patch(
            "run_all_burt.config.PROMPT_VERSION",
            "VTest",
        ):
            return_code = run_all_burt.run_evaluator("python")

        self.assertEqual(return_code, 0)
        mock_run.assert_called_once_with(
            ["python", "-m", "evaluator.runner", "logs/VTest"],
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
