import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from burt_core import burt
from observability.observability_sinks import LocalFileSink, RedisThenFileSink
from burt_core.state import BugAgentState


class BurtRuntimeContextTests(unittest.TestCase):
    @patch("burt_core.burt.ChatOpenAI")
    def test_create_runtime_context_returns_distinct_request_local_objects(
        self,
        mock_chat_openai,
    ):
        model_a = object()
        model_b = object()
        mock_chat_openai.side_effect = [model_a, model_b]

        context_a = burt.create_runtime_context(
            session_id="session-a",
            log_path=Path("logs/test/session-a.log"),
        )
        context_b = burt.create_runtime_context(
            session_id="session-b",
            log_path=Path("logs/test/session-b.log"),
        )

        self.assertEqual(context_a.session_id, "session-a")
        self.assertEqual(context_b.session_id, "session-b")
        self.assertNotEqual(context_a.logger.filepath, context_b.logger.filepath)
        self.assertEqual(context_a.logger.session_id, "session-a")
        self.assertEqual(context_b.logger.session_id, "session-b")
        self.assertIsNot(context_a.logger, context_b.logger)
        self.assertIsInstance(context_a.sink, LocalFileSink)
        self.assertIsInstance(context_b.sink, LocalFileSink)
        self.assertIs(context_a.logger.sink, context_a.sink)
        self.assertIs(context_b.logger.sink, context_b.sink)
        self.assertIsNot(context_a.sink, context_b.sink)
        self.assertIsNot(context_a.usage_callback, context_b.usage_callback)
        self.assertIs(context_a.model, model_a)
        self.assertIs(context_b.model, model_b)

    @patch("burt_core.burt.ChatOpenAI")
    def test_create_runtime_context_builds_redis_then_file_sink(
        self,
        mock_chat_openai,
    ):
        mock_chat_openai.return_value = object()
        redis_client = MagicMock()

        context = burt.create_runtime_context(
            session_id="session-a",
            log_path=Path("logs/test/session-a.log"),
            sink_mode="redis_then_file",
            redis_client=redis_client,
        )

        self.assertIsInstance(context.sink, RedisThenFileSink)
        self.assertIs(context.sink.redis_client, redis_client)
        self.assertEqual(
            context.sink.filepath,
            context.logger.filepath,
        )
        self.assertIs(context.logger.sink, context.sink)

    @patch("burt_core.burt.ChatOpenAI")
    def test_create_runtime_context_redis_then_file_mode_requires_redis_client(
        self,
        mock_chat_openai,
    ):
        mock_chat_openai.return_value = object()

        with self.assertRaisesRegex(
            ValueError,
            "redis_client is required when sink_mode is 'redis_then_file'",
        ):
            burt.create_runtime_context(
                session_id="session-a",
                log_path=Path("logs/test/session-a.log"),
                sink_mode="redis_then_file",
            )

    @patch("burt_core.burt.ChatOpenAI")
    def test_create_runtime_context_rejects_unknown_sink_mode(
        self,
        mock_chat_openai,
    ):
        mock_chat_openai.return_value = object()

        with self.assertRaisesRegex(ValueError, "Unsupported sink_mode: invalid"):
            burt.create_runtime_context(
                session_id="session-a",
                log_path=Path("logs/test/session-a.log"),
                sink_mode="invalid",
            )

    @patch("burt_core.burt.fetch_graph_data", return_value=("app graph", "Test App", "screens"))
    def test_load_bug_graph_context_only_returns_graph_data(
        self,
        mock_fetch_graph_data,
    ):
        result = burt.load_bug_graph_context(current_bug=42)

        self.assertEqual(result, ("app graph", "Test App", "screens"))
        mock_fetch_graph_data.assert_called_once_with(bug_id=42)

    @patch(
        "burt_core.burt.llm_extract",
        return_value=SimpleNamespace(model_dump=lambda *args, **kwargs: {}),
    )
    def test_information_element_extraction_uses_runtime_context_model(
        self,
        mock_llm_extract,
    ):
        runtime_context = SimpleNamespace(logger=MagicMock(), model=object())
        state = BugAgentState()
        state.messages = [SimpleNamespace(content="first"), SimpleNamespace(content="second")]
        config = {
            "configurable": {
                "app_name": "Test App",
                "runtime_context": runtime_context,
            }
        }

        burt.information_element_extraction.__wrapped__(state, config)

        mock_llm_extract.assert_called_once()
        self.assertIs(mock_llm_extract.call_args.kwargs["model"], runtime_context.model)

    @patch(
        "burt_core.burt.generate_report",
        return_value={"full_report": {"title": "Final report"}},
    )
    def test_generate_final_report_uses_runtime_context_model(self, mock_generate_report):
        runtime_context = SimpleNamespace(logger=MagicMock(), model=object())
        state = BugAgentState()
        state.BugInfo = MagicMock()
        config = {
            "configurable": {
                "transitions": "app graph",
                "app_name": "Test App",
                "runtime_context": runtime_context,
            }
        }

        with patch("burt_core.burt.find_unknown_or_ambiguous", return_value=set()):
            result = burt.generate_final_report.__wrapped__(state, config)

        self.assertEqual(result, {"full_report": {"title": "Final report"}})
        mock_generate_report.assert_called_once_with(
            state.BugInfo,
            "app graph",
            runtime_context.model,
            "Test App",
        )


if __name__ == "__main__":
    unittest.main()
