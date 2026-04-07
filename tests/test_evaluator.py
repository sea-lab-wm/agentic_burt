import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluator.parsing import REPO_ROOT, build_log_context
from evaluator.runner import evaluate_log


class EvaluatorTests(unittest.TestCase):
    def _write_log(self, records: list[dict], filename: str = "bug10_LC_LP.log") -> Path:
        tempdir = tempfile.TemporaryDirectory(dir=REPO_ROOT)
        self.addCleanup(tempdir.cleanup)
        log_path = Path(tempdir.name) / "logs" / "VTest" / filename
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "\n".join(json.dumps(record, indent=2) for record in records) + "\n",
            encoding="utf-8",
        )
        return log_path

    @staticmethod
    def _generate_report_record() -> dict:
        return {
            "turn": 1,
            "actions": [
                {
                    "entity": "bot",
                    "action_name": "generate_report",
                    "output": {
                        "full_report": {
                            "title": "Bug title",
                            "observed_behavior": "Observed behavior",
                            "expected_behavior": "Expected behavior",
                            "steps_to_reproduce": "1. Do thing",
                        },
                        "extracted_information_elements": {
                            "buggy_behavior": "Observed behavior"
                        },
                    },
                    "meta_data": {"latency": "0.1 s", "node_token_consumption": None},
                }
            ],
        }

    @staticmethod
    def _summary_record(**overrides) -> dict:
        summary = {
            "record_type": "conversation_summary",
            "conversation_id": "10",
            "started_at": "2026-04-07T00:00:00+00:00",
            "ended_at": "2026-04-07T00:00:05+00:00",
            "total_latency_seconds": 5.0,
            "total_conversation_turns": 2,
            "token_consumption": {
                "input_tokens": 10,
                "output_tokens": 4,
                "total_tokens": 14,
            },
        }
        summary.update(overrides)
        return summary

    @staticmethod
    def _ground_truth_rows() -> dict[int, dict[str, str]]:
        return {
            10: {
                "bug_id": "10",
                "app_name": "Test App",
                "info_elements_gt": "gt info",
                "S2R_ground_truth": "1. gt step",
            }
        }

    def test_build_log_context_extracts_summary_metrics(self):
        log_path = self._write_log(
            [self._generate_report_record(), self._summary_record()]
        )

        context = build_log_context(log_path, self._ground_truth_rows())

        self.assertEqual(context["total_input_tokens_consumed"], 10)
        self.assertEqual(context["total_output_tokens_consumed"], 4)
        self.assertEqual(context["total_tokens_consumed"], 14)
        self.assertEqual(context["total_time_seconds_of_conversation"], 5.0)
        self.assertEqual(context["total_conversation_turns"], 2)

    def test_build_log_context_defaults_summary_metrics_to_null_when_missing(self):
        log_path = self._write_log([self._generate_report_record()])

        context = build_log_context(log_path, self._ground_truth_rows())

        self.assertIsNone(context["total_input_tokens_consumed"])
        self.assertIsNone(context["total_output_tokens_consumed"])
        self.assertIsNone(context["total_tokens_consumed"])
        self.assertIsNone(context["total_time_seconds_of_conversation"])
        self.assertIsNone(context["total_conversation_turns"])
        self.assertEqual(context["parse_status"], "ok")

    def test_build_log_context_handles_partial_summary_record(self):
        partial_summary = self._summary_record(
            total_conversation_turns=None,
            token_consumption={"input_tokens": 7},
        )
        log_path = self._write_log([self._generate_report_record(), partial_summary])

        context = build_log_context(log_path, self._ground_truth_rows())

        self.assertEqual(context["total_input_tokens_consumed"], 7)
        self.assertIsNone(context["total_output_tokens_consumed"])
        self.assertIsNone(context["total_tokens_consumed"])
        self.assertEqual(context["total_time_seconds_of_conversation"], 5.0)
        self.assertIsNone(context["total_conversation_turns"])

    def test_evaluate_log_includes_summary_metrics(self):
        log_path = self._write_log(
            [self._generate_report_record(), self._summary_record()]
        )
        model = object()

        with patch(
            "evaluator.runner.extract_information_elements_from_OB_EB",
            return_value={"buggy_behavior": "Observed behavior"},
        ), patch(
            "evaluator.runner.judge_information_elements",
            return_value=type("JudgeResult", (), {"model_dump": lambda self: {"buggy_behavior": "Correct"}})(),
        ), patch(
            "evaluator.runner.judge_s2r",
            return_value=type(
                "S2RResult",
                (),
                {"steps": [type("Step", (), {"model_dump": lambda self: {"generated_step": "1. Do thing"}})()]},
            )(),
        ):
            result = evaluate_log(log_path, model, self._ground_truth_rows())

        self.assertEqual(result["total_input_tokens_consumed"], 10)
        self.assertEqual(result["total_output_tokens_consumed"], 4)
        self.assertEqual(result["total_tokens_consumed"], 14)
        self.assertEqual(result["total_time_seconds_of_conversation"], 5.0)
        self.assertEqual(result["total_conversation_turns"], 2)

    def test_evaluate_log_parse_error_keeps_summary_metrics_independent(self):
        log_path = self._write_log([self._summary_record()])
        model = object()

        result = evaluate_log(log_path, model, self._ground_truth_rows())

        self.assertEqual(result["status"], "parse_error")
        self.assertEqual(result["parse_status"], "missing_generate_report")
        self.assertEqual(result["total_input_tokens_consumed"], 10)
        self.assertEqual(result["total_output_tokens_consumed"], 4)
        self.assertEqual(result["total_tokens_consumed"], 14)
        self.assertEqual(result["total_time_seconds_of_conversation"], 5.0)
        self.assertEqual(result["total_conversation_turns"], 2)


if __name__ == "__main__":
    unittest.main()
