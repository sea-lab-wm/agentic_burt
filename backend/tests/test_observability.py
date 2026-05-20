import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage

from observability.logging_runtime import (
    ObservabilityTokenCallback,
    TurnLogger,
    log_action,
)
from observability.observability_models import (
    ActionName,
    ConversationTurn,
    Entity,
    LLMUsageEvent,
    MetaData,
)
from observability.observability_sinks import LocalFileSink, RedisThenFileSink


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
    def _log_user_description(logger: TurnLogger, text: str):
        @log_action(entity=Entity.user, action_name=ActionName.user_description)
        def user_node(runtime_context):
            return {"messages": HumanMessage(content=text)}

        return user_node(runtime_context=SimpleNamespace(logger=logger, model=object()))

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

    @staticmethod
    def _persist_current_turn(
        logger: TurnLogger,
        sink: LocalFileSink,
        *,
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> None:
        if logger.current_turn is None:
            raise AssertionError("Expected an active turn to persist.")
        if started_at is not None:
            logger.current_turn.started_at = started_at
        if ended_at is not None:
            logger.current_turn.ended_at = ended_at
        sink.append_turn(logger.build_turn_record())
        logger.reset_turn()

    def test_single_node_token_consumption(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger(filepath=str(Path(tmpdir) / "test.log"), session_id="sess-1")
            runtime_context = SimpleNamespace(logger=logger, model=object())
            self._log_user_description(logger, "initial bug description")

            @log_action(entity=Entity.bot, action_name=ActionName.follow_up)
            def node(runtime_context):
                logger.record_llm_usage(
                    LLMUsageEvent(
                        input_tokens=10,
                        output_tokens=4,
                        total_tokens=14,
                        usage_available=True,
                    )
                )
                return {"ok": True}

            node(runtime_context=runtime_context)
            action = logger.current_turn.actions[1]
            self.assertIsNotNone(action.meta_data.node_token_consumption)
            self.assertEqual(action.meta_data.node_token_consumption.input_tokens, 10)
            self.assertEqual(action.meta_data.node_token_consumption.output_tokens, 4)
            self.assertEqual(action.meta_data.node_token_consumption.total_tokens, 14)
            self.assertEqual(action.meta_data.node_token_consumption.llm_calls, 1)

    def test_multiple_llm_calls_sum_within_node(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger(filepath=str(Path(tmpdir) / "test.log"), session_id="sess-2")
            runtime_context = SimpleNamespace(logger=logger, model=object())
            self._log_user_description(logger, "initial bug description")

            @log_action(entity=Entity.bot, action_name=ActionName.extract_and_update)
            def node(runtime_context):
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

            node(runtime_context=runtime_context)
            summary = logger.current_turn.actions[1].meta_data.node_token_consumption
            self.assertEqual(summary.input_tokens, 8)
            self.assertEqual(summary.output_tokens, 9)
            self.assertEqual(summary.total_tokens, 17)
            self.assertEqual(summary.llm_calls, 2)
            self.assertEqual(summary.llm_calls_with_usage, 2)
            self.assertEqual(summary.llm_calls_missing_usage, 0)

    def test_missing_usage_nulls_token_totals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger(filepath=str(Path(tmpdir) / "test.log"), session_id="sess-3")
            runtime_context = SimpleNamespace(logger=logger, model=object())
            self._log_user_description(logger, "initial bug description")

            @log_action(
                entity=Entity.bot,
                action_name=ActionName.information_element_extraction,
            )
            def node(runtime_context):
                logger.record_llm_usage(
                    LLMUsageEvent(
                        input_tokens=None,
                        output_tokens=None,
                        total_tokens=None,
                        usage_available=False,
                    )
                )
                return {"ok": True}

            node(runtime_context=runtime_context)
            summary = logger.current_turn.actions[1].meta_data.node_token_consumption
            self.assertIsNone(summary.input_tokens)
            self.assertIsNone(summary.output_tokens)
            self.assertIsNone(summary.total_tokens)
            self.assertEqual(summary.llm_calls, 1)
            self.assertEqual(summary.llm_calls_with_usage, 0)
            self.assertEqual(summary.llm_calls_missing_usage, 1)

    def test_non_llm_node_has_no_node_token_consumption(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger(filepath=str(Path(tmpdir) / "test.log"), session_id="sess-4")
            runtime_context = SimpleNamespace(logger=logger, model=object())
            self._log_user_description(logger, "initial bug description")

            @log_action(entity=Entity.bot, action_name=ActionName.evaluate)
            def node(runtime_context):
                return {"ok": True}

            node(runtime_context=runtime_context)
            summary = logger.current_turn.actions[1].meta_data.node_token_consumption
            self.assertIsNone(summary)

    def test_non_user_action_requires_existing_turn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger(filepath=str(Path(tmpdir) / "test.log"), session_id="sess-pre-user")
            runtime_context = SimpleNamespace(logger=logger, model=object())

            @log_action(entity=Entity.bot, action_name=ActionName.evaluate)
            def node(runtime_context):
                return {"ok": True}

            with self.assertRaisesRegex(
                ValueError, "Cannot log non-user action before the first user_description"
            ):
                node(runtime_context=runtime_context)

    def test_user_turns_are_one_indexed_and_increment_per_description_after_reset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger(filepath=str(Path(tmpdir) / "test.log"), session_id="sess-turns")

            first = self._log_user_description(logger, "initial description")
            self.assertEqual(first["messages"].content, "initial description")
            self.assertEqual(logger.num_turns, 1)
            self.assertIsNotNone(logger.current_turn)
            self.assertEqual(logger.current_turn.session_id, "sess-turns")
            self.assertEqual(logger.current_turn.turn, 1)
            self.assertIsNotNone(logger.current_turn.started_at)
            self.assertIsNone(logger.current_turn.ended_at)
            self.assertEqual(
                logger.current_turn.actions[0].action_name, ActionName.user_description
            )

            logger.reset_turn()
            self._log_user_description(logger, "follow-up description")
            self.assertEqual(logger.num_turns, 2)
            self.assertIsNotNone(logger.current_turn)
            self.assertEqual(logger.current_turn.turn, 2)

    def test_user_description_helper_returns_human_message_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger(filepath=str(Path(tmpdir) / "test.log"), session_id="sess-helper")

            update = self._log_user_description(logger, "describe the bug")
            self.assertIn("messages", update)
            self.assertIsInstance(update["messages"], HumanMessage)
            self.assertEqual(update["messages"].content, "describe the bug")
            self.assertEqual(logger.current_turn.actions[0].entity, Entity.user)

    def test_build_turn_record_returns_copy_and_reset_clears_turn_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger(filepath=str(Path(tmpdir) / "test.log"), session_id="sess-turn-copy")
            self._log_user_description(logger, "describe the bug")
            turn_record = logger.build_turn_record()

            self.assertEqual(turn_record.session_id, "sess-turn-copy")
            self.assertEqual(turn_record.turn, 1)
            self.assertEqual(turn_record.actions[0].action_name, ActionName.user_description)

            logger.reset_turn()
            self.assertIsNone(logger.current_turn)
            self.assertEqual(logger.num_turns, 1)

    def test_local_file_sink_finalize_session_builds_summary_from_turn_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            sink = LocalFileSink(filepath=log_path)
            logger = TurnLogger(filepath=str(log_path), session_id="sess-5", sink=sink)
            callback = ObservabilityTokenCallback(logger=logger)
            runtime_context = SimpleNamespace(logger=logger, model=object())
            base_time = datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc)

            self._log_user_description(logger, "initial bug description")

            @log_action(entity=Entity.bot, action_name=ActionName.clarity_check)
            def node(runtime_context):
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

            node(runtime_context=runtime_context)
            self._persist_current_turn(
                logger,
                sink,
                started_at=base_time.isoformat(),
                ended_at=(base_time + timedelta(seconds=2)).isoformat(),
            )

            self._log_user_description(logger, "follow-up bug description")

            logger.add_action_to_turn(
                entity=Entity.bot,
                action_name=ActionName.evaluate,
                output={"ok": True},
                meta_data=MetaData(latency="0.1 s", node_token_consumption=None),
            )
            logger.add_action_to_turn(
                entity=Entity.bot,
                action_name=ActionName.generate_report,
                output={"full_report": {"title": "Bug title"}},
                meta_data=MetaData(
                    latency="0.2 s",
                    node_token_consumption={
                        "input_tokens": 8,
                        "output_tokens": 3,
                        "total_tokens": 11,
                        "llm_calls": 1,
                        "llm_calls_with_usage": 1,
                        "llm_calls_missing_usage": 0,
                    },
                ),
            )
            self._persist_current_turn(
                logger,
                sink,
                started_at=(base_time + timedelta(seconds=10)).isoformat(),
                ended_at=(base_time + timedelta(seconds=11)).isoformat(),
            )

            sink.finalize_session(
                session_id="sess-5",
                final_report={"title": "Bug title"},
                run_metadata={
                    "bug_id": 10,
                    "description_level": "LC_LP",
                    "input_source": "BugScribe_dev",
                    "runtime": "cli",
                },
            )

            records = self._parse_json_stream(log_path.read_text())
            self.assertEqual(records[0]["session_id"], "sess-5")
            self.assertEqual(records[0]["turn"], 1)
            self.assertEqual(records[0]["started_at"], base_time.isoformat())
            self.assertEqual(records[0]["ended_at"], (base_time + timedelta(seconds=2)).isoformat())
            self.assertEqual(records[0]["actions"][0]["action_name"], "user_description")
            self.assertEqual(records[0]["actions"][1]["action_name"], "clarity_check")
            self.assertEqual(records[1]["turn"], 2)
            self.assertEqual(records[1]["actions"][2]["action_name"], "generate_report")
            self.assertEqual(records[1]["actions"][2]["output"]["full_report"]["title"], "Bug title")
            self.assertEqual(records[2]["record_type"], "final_report")
            self.assertEqual(records[2]["final_report"]["title"], "Bug title")
            self.assertEqual(records[3]["record_type"], "conversation_summary")
            self.assertEqual(records[3]["session_id"], "sess-5")
            self.assertEqual(
                records[3]["run_metadata"],
                {
                    "bug_id": 10,
                    "description_level": "LC_LP",
                    "input_source": "BugScribe_dev",
                    "runtime": "cli",
                },
            )
            self.assertEqual(records[3]["started_at"], base_time.isoformat())
            self.assertEqual(records[3]["ended_at"], (base_time + timedelta(seconds=11)).isoformat())
            self.assertEqual(records[3]["total_wall_clock_seconds"], 11.0)
            self.assertEqual(records[3]["total_turn_processing_seconds"], 3.0)
            self.assertEqual(records[3]["total_conversation_turns"], 2)
            self.assertEqual(records[3]["token_consumption"]["input_tokens"], 14)
            self.assertEqual(records[3]["token_consumption"]["output_tokens"], 7)
            self.assertEqual(records[3]["token_consumption"]["total_tokens"], 21)
            self.assertEqual(records[3]["token_consumption"]["llm_calls"], 2)
            self.assertEqual(records[3]["token_consumption"]["llm_calls_with_usage"], 2)
            self.assertEqual(records[3]["token_consumption"]["llm_calls_missing_usage"], 0)

    def test_redis_then_file_sink_append_turn_pushes_json_to_session_list(self):
        redis_client = MagicMock()
        sink = RedisThenFileSink(redis_client=redis_client, filepath=Path("ignored.log"))
        turn_record = ConversationTurn(
            session_id="sess-redis",
            turn=1,
            started_at="2026-04-07T00:00:00+00:00",
            ended_at="2026-04-07T00:00:01+00:00",
            actions=[],
        )

        sink.append_turn(turn_record)

        redis_client.rpush.assert_called_once_with(
            "burt:session-log:sess-redis",
            turn_record.model_dump_json(),
        )

    def test_redis_then_file_sink_finalize_session_rebuilds_log_and_deletes_staging_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            redis_client = MagicMock()
            sink = RedisThenFileSink(redis_client=redis_client, filepath=log_path)
            base_time = datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc)

            turn_one = {
                "session_id": "sess-redis",
                "turn": 1,
                "started_at": base_time.isoformat(),
                "ended_at": (base_time + timedelta(seconds=2)).isoformat(),
                "actions": [
                    {
                        "entity": "user",
                        "action_name": "user_description",
                        "output": "initial bug description",
                        "meta_data": {"latency": "0.0 s", "node_token_consumption": None},
                    },
                    {
                        "entity": "bot",
                        "action_name": "clarity_check",
                        "output": {"ok": True},
                        "meta_data": {
                            "latency": "0.1 s",
                            "node_token_consumption": {
                                "input_tokens": 6,
                                "output_tokens": 4,
                                "total_tokens": 10,
                                "llm_calls": 1,
                                "llm_calls_with_usage": 1,
                                "llm_calls_missing_usage": 0,
                            },
                        },
                    },
                ],
            }
            turn_two = {
                "session_id": "sess-redis",
                "turn": 2,
                "started_at": (base_time + timedelta(seconds=10)).isoformat(),
                "ended_at": (base_time + timedelta(seconds=11)).isoformat(),
                "actions": [
                    {
                        "entity": "user",
                        "action_name": "user_description",
                        "output": "follow-up description",
                        "meta_data": {"latency": "0.0 s", "node_token_consumption": None},
                    },
                    {
                        "entity": "bot",
                        "action_name": "generate_report",
                        "output": {"full_report": {"title": "Bug title"}},
                        "meta_data": {
                            "latency": "0.2 s",
                            "node_token_consumption": {
                                "input_tokens": 8,
                                "output_tokens": 3,
                                "total_tokens": 11,
                                "llm_calls": 1,
                                "llm_calls_with_usage": 1,
                                "llm_calls_missing_usage": 0,
                            },
                        },
                    },
                ],
            }
            redis_client.lrange.return_value = [
                json.dumps(turn_one),
                json.dumps(turn_two),
            ]

            sink.finalize_session(
                session_id="sess-redis",
                final_report={"title": "Bug title"},
                run_metadata={
                    "bug_id": 2,
                    "description_level": None,
                    "input_source": "user",
                    "runtime": "api",
                },
            )

            records = self._parse_json_stream(log_path.read_text())
            self.assertEqual(records[0]["turn"], 1)
            self.assertEqual(records[1]["turn"], 2)
            self.assertEqual(records[2]["record_type"], "final_report")
            self.assertEqual(records[2]["final_report"]["title"], "Bug title")
            self.assertEqual(records[3]["record_type"], "conversation_summary")
            self.assertEqual(
                records[3]["run_metadata"],
                {
                    "bug_id": 2,
                    "description_level": None,
                    "input_source": "user",
                    "runtime": "api",
                },
            )
            self.assertEqual(records[3]["started_at"], base_time.isoformat())
            self.assertEqual(records[3]["ended_at"], (base_time + timedelta(seconds=11)).isoformat())
            self.assertEqual(records[3]["total_wall_clock_seconds"], 11.0)
            self.assertEqual(records[3]["total_turn_processing_seconds"], 3.0)
            self.assertEqual(records[3]["token_consumption"]["input_tokens"], 14)
            self.assertEqual(records[3]["token_consumption"]["output_tokens"], 7)
            self.assertEqual(records[3]["token_consumption"]["total_tokens"], 21)
            redis_client.lrange.assert_called_once_with("burt:session-log:sess-redis", 0, -1)
            redis_client.delete.assert_called_once_with("burt:session-log:sess-redis")

    def test_redis_then_file_sink_finalize_session_does_not_delete_staging_list_if_write_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            redis_client = MagicMock()
            filepath = Path(tmpdir) / "test.log"
            sink = RedisThenFileSink(redis_client=redis_client, filepath=filepath)
            redis_client.lrange.return_value = [
                json.dumps(
                    {
                        "session_id": "sess-redis",
                        "turn": 1,
                        "started_at": "2026-04-07T00:00:00+00:00",
                        "ended_at": "2026-04-07T00:00:01+00:00",
                        "actions": [],
                    }
                )
            ]

            with patch("pathlib.Path.open", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    sink.finalize_session(
                        session_id="sess-redis",
                        final_report={"title": "Bug title"},
                    )

            redis_client.delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
