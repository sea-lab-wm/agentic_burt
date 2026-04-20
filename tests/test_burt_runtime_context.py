import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import burt
from observability.observability_sinks import LocalFileSink, RedisThenFileSink
from state import BugAgentState


class BurtRuntimeContextTests(unittest.TestCase):
    @patch("burt.ChatOpenAI")
    def test_create_runtime_context_returns_distinct_request_local_objects(
        self,
        mock_chat_openai,
    ):
        model_a = object()
        model_b = object()
        mock_chat_openai.side_effect = [model_a, model_b]

        context_a = burt.create_runtime_context(
            session_id="session-a",
            bug_id=10,
            description_level="LC_LP",
        )
        context_b = burt.create_runtime_context(
            session_id="session-b",
            bug_id=10,
            description_level="LC_LP",
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

    @patch("burt.ChatOpenAI")
    def test_create_runtime_context_builds_redis_then_file_sink(
        self,
        mock_chat_openai,
    ):
        mock_chat_openai.return_value = object()
        redis_client = MagicMock()

        context = burt.create_runtime_context(
            session_id="session-a",
            bug_id=10,
            description_level="LC_LP",
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

    @patch("burt.ChatOpenAI")
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
                bug_id=10,
                description_level="LC_LP",
                sink_mode="redis_then_file",
            )

    @patch("burt.ChatOpenAI")
    def test_create_runtime_context_rejects_unknown_sink_mode(
        self,
        mock_chat_openai,
    ):
        mock_chat_openai.return_value = object()

        with self.assertRaisesRegex(ValueError, "Unsupported sink_mode: invalid"):
            burt.create_runtime_context(
                session_id="session-a",
                bug_id=10,
                description_level="LC_LP",
                sink_mode="invalid",
            )

    @patch("burt.fetch_graph_data", return_value=("app graph", "Test App", "screens"))
    @patch("burt.SessionLocal")
    def test_load_bug_graph_context_only_returns_graph_data(
        self,
        mock_session_local,
        mock_fetch_graph_data,
    ):
        session = MagicMock()
        mock_session_local.return_value = session

        result = burt.load_bug_graph_context(current_bug=42)

        self.assertEqual(result, ("app graph", "Test App", "screens"))
        mock_session_local.assert_called_once_with()
        mock_fetch_graph_data.assert_called_once_with(session=session, bug_id=42)
        session.close.assert_called_once_with()

    @patch(
        "burt.llm_extract",
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
        "burt.generate_report",
        return_value={"full_report": {"title": "Final report"}},
    )
    def test_generate_final_report_uses_runtime_context_model(self, mock_generate_report):
        runtime_context = SimpleNamespace(logger=MagicMock(), model=object())
        state = BugAgentState()
        state.BugInfo = MagicMock()
        config = {
            "configurable": {
                "app_graph": "app graph",
                "app_name": "Test App",
                "runtime_context": runtime_context,
            }
        }

        with patch("burt.find_unknown_or_ambiguous", return_value=set()):
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
