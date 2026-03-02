import json
import tempfile
import time
import unittest
from pathlib import Path

from observability import (
    ActionName,
    ConversationLogger,
    Entity,
    LLMUsageEvent,
    ObservabilityTokenCallback,
    log_action,
)


class FakeMessage:
    def __init__(self, usage_metadata=None, response_metadata=None):
        self.usage_metadata = usage_metadata or {}
        self.response_metadata = response_metadata or {}


class FakeGeneration:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, llm_output=None, generations=None):
        self.llm_output = llm_output or {}
        self.generations = generations or []


class ObservabilityTests(unittest.TestCase):
    @staticmethod
    def _parse_json_stream(text: str):
        decoder = json.JSONDecoder()
        idx = 0
        length = len(text)
        parsed = []

        while idx < length:
            while idx < length and text[idx].isspace():
                idx += 1
            if idx >= length:
                break
            obj, offset = decoder.raw_decode(text, idx)
            parsed.append(obj)
            idx = offset

        return parsed

    def test_single_node_token_consumption(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ConversationLogger(
                filepath=str(Path(tmpdir) / "test.log"), conversation_id="conv-1"
            )

            @log_action(logger=logger, entity=Entity.bot, action_name=ActionName.follow_up)
            def node():
                logger.record_llm_usage(
                    LLMUsageEvent(
                        input_tokens=10,
                        output_tokens=4,
                        total_tokens=14,
                        usage_available=True,
                    )
                )
                return {"ok": True}

            node()
            action = logger.conversation[0].actions[0]
            self.assertIsNotNone(action.meta_data.node_token_consumption)
            self.assertEqual(action.meta_data.node_token_consumption.input_tokens, 10)
            self.assertEqual(action.meta_data.node_token_consumption.output_tokens, 4)
            self.assertEqual(action.meta_data.node_token_consumption.total_tokens, 14)
            self.assertEqual(action.meta_data.node_token_consumption.llm_calls, 1)

    def test_multiple_llm_calls_sum_within_node(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ConversationLogger(
                filepath=str(Path(tmpdir) / "test.log"), conversation_id="conv-2"
            )

            @log_action(
                logger=logger, entity=Entity.bot, action_name=ActionName.extract_and_update
            )
            def node():
                logger.record_llm_usage(
                    LLMUsageEvent(
                        input_tokens=5,
                        output_tokens=7,
                        total_tokens=12,
                        usage_available=True,
                    )
                )
                logger.record_llm_usage(
                    LLMUsageEvent(
                        input_tokens=3,
                        output_tokens=2,
                        total_tokens=5,
                        usage_available=True,
                    )
                )
                return {"ok": True}

            node()
            summary = logger.conversation[0].actions[0].meta_data.node_token_consumption
            self.assertEqual(summary.input_tokens, 8)
            self.assertEqual(summary.output_tokens, 9)
            self.assertEqual(summary.total_tokens, 17)
            self.assertEqual(summary.llm_calls, 2)
            self.assertEqual(summary.llm_calls_with_usage, 2)
            self.assertEqual(summary.llm_calls_missing_usage, 0)

    def test_missing_usage_nulls_token_totals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ConversationLogger(
                filepath=str(Path(tmpdir) / "test.log"), conversation_id="conv-3"
            )

            @log_action(
                logger=logger,
                entity=Entity.bot,
                action_name=ActionName.information_element_extraction,
            )
            def node():
                logger.record_llm_usage(
                    LLMUsageEvent(
                        input_tokens=None,
                        output_tokens=None,
                        total_tokens=None,
                        usage_available=False,
                    )
                )
                return {"ok": True}

            node()
            summary = logger.conversation[0].actions[0].meta_data.node_token_consumption
            self.assertIsNone(summary.input_tokens)
            self.assertIsNone(summary.output_tokens)
            self.assertIsNone(summary.total_tokens)
            self.assertEqual(summary.llm_calls, 1)
            self.assertEqual(summary.llm_calls_with_usage, 0)
            self.assertEqual(summary.llm_calls_missing_usage, 1)

    def test_non_llm_node_has_no_node_token_consumption(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ConversationLogger(
                filepath=str(Path(tmpdir) / "test.log"), conversation_id="conv-4"
            )

            @log_action(logger=logger, entity=Entity.bot, action_name=ActionName.evaluate)
            def node():
                return {"ok": True}

            node()
            summary = logger.conversation[0].actions[0].meta_data.node_token_consumption
            self.assertIsNone(summary)

    def test_summary_record_appended_and_totals_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            logger = ConversationLogger(filepath=str(log_path), conversation_id="conv-5")
            callback = ObservabilityTokenCallback(logger=logger)

            logger.start_conversation()

            @log_action(
                logger=logger, entity=Entity.bot, action_name=ActionName.clarity_check
            )
            def node():
                fake_response = FakeResponse(
                    llm_output={
                        "token_usage": {
                            "prompt_tokens": 6,
                            "completion_tokens": 4,
                            "total_tokens": 10,
                        },
                        "model_name": "gpt-test",
                    }
                )
                callback.on_llm_end(fake_response)
                return {"ok": True}

            node()
            time.sleep(0.01)
            logger.finish_conversation()
            logger.write_log()

            lines = self._parse_json_stream(log_path.read_text())
            self.assertGreaterEqual(len(lines), 2)
            summary = lines[-1]
            self.assertEqual(summary["record_type"], "conversation_summary")
            self.assertGreater(summary["total_latency_seconds"], 0)
            self.assertEqual(summary["token_consumption"]["input_tokens"], 6)
            self.assertEqual(summary["token_consumption"]["output_tokens"], 4)
            self.assertEqual(summary["token_consumption"]["total_tokens"], 10)


if __name__ == "__main__":
    unittest.main()
