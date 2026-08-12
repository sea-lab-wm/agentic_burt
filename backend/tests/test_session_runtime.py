import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, sentinel

from app.services import burt_runtime


class StartConversationTests(unittest.TestCase):
    def _runtime_context(self):
        return SimpleNamespace(
            sink=MagicMock(),
            logger=SimpleNamespace(filepath=Path("logs/test.log")),
        )

    @patch("app.services.burt_runtime._flush_active_turn")
    @patch("app.services.burt_runtime.create_session_record")
    @patch("app.services.burt_runtime.create_runtime_context")
    @patch("app.services.burt_runtime.build_burt_graph")
    @patch("app.services.burt_runtime.RedisSaver.from_conn_string")
    @patch("app.services.burt_runtime.BugAgentState", return_value=sentinel.initial_state)
    @patch(
        "app.services.burt_runtime.ingest_user_description",
        return_value={"messages": sentinel.initial_message_update},
    )
    @patch(
        "app.services.burt_runtime.load_bug_graph_context",
        return_value=("transitions", "Test App", "screen descriptions"),
    )
    @patch("app.services.burt_runtime.uuid4", return_value="session-123")
    def test_start_conversation_persists_interrupt_response(
        self,
        mock_uuid4,
        mock_load_bug_graph_context,
        mock_ingest_user_description,
        mock_bug_agent_state,
        mock_from_conn_string,
        mock_build_burt_graph,
        mock_create_runtime_context,
        mock_create_session_record,
        mock_flush_active_turn,
    ):
        runtime_context = self._runtime_context()
        mock_create_runtime_context.return_value = runtime_context
        # Simulate the RedisSaver context manager yielding a checkpointer instance.
        checkpointer = MagicMock()
        # Simulate the compiled graph returned by build_burt_graph(checkpointer).
        graph = MagicMock()
        # Returning __interrupt__ means the conversation should remain open and ask a follow-up question.
        graph.invoke.return_value = {
            "__interrupt__": [{"Follow Up Question": "What screen were you on?"}]
        }
        mock_build_burt_graph.return_value = graph
        context_manager = MagicMock()
        context_manager.__enter__.return_value = checkpointer
        context_manager.__exit__.return_value = False
        mock_from_conn_string.return_value = context_manager

        response = burt_runtime.start_conversation(
            bug_id=42,
            user_description="initial bug description",
        )

        # The start flow should persist an awaiting_user response tied to the generated session id.
        self.assertEqual(response.session_id, "session-123")
        self.assertEqual(response.status, "awaiting_user")
        self.assertEqual(response.question, "What screen were you on?")
        self.assertIsNone(response.final_report)
        mock_load_bug_graph_context.assert_called_once_with(
            current_bug=42,
        )
        mock_create_runtime_context.assert_called_once_with(
            session_id="session-123",
            log_path=Path("logs") / str(burt_runtime.config.PROMPT_VERSION) / "session-123.log",
            sink_mode="redis_then_file",
            redis_client=burt_runtime.redis_client,
        )
        mock_ingest_user_description.assert_called_once_with(
            "initial bug description",
            runtime_context=runtime_context,
        )
        # A first message is a normal conversation, so follow-ups stay available.
        mock_bug_agent_state.assert_called_once_with(
            messages=[sentinel.initial_message_update],
            single_pass=False,
        )
        checkpointer.setup.assert_called_once_with()
        mock_build_burt_graph.assert_called_once_with(checkpointer)
        graph.invoke.assert_called_once_with(
            sentinel.initial_state,
            config={
                "configurable": {
                    "transitions": "transitions",
                    "app_name": "Test App",
                    "screen_descriptions": "screen descriptions",
                    "thread_id": "session-123",
                    "runtime_context": runtime_context,
                }
            },
        )
        mock_flush_active_turn.assert_called_once_with(runtime_context)
        runtime_context.sink.finalize_session.assert_not_called()
        checkpointer.delete_thread.assert_not_called()
        mock_create_session_record.assert_called_once_with(
            {
                "session_id": "session-123",
                "bug_id": 42,
                "status": "awaiting_user",
                "question": "What screen were you on?",
                "final_report": None,
                "draft_revision": 0,
                "final_revision": 0,
                "edits_remaining": 3,
            }
        )
        mock_uuid4.assert_called_once_with()

    @patch("app.services.burt_runtime._flush_active_turn")
    @patch("app.services.burt_runtime.create_session_record")
    @patch("app.services.burt_runtime.create_runtime_context")
    @patch("app.services.burt_runtime.build_burt_graph")
    @patch("app.services.burt_runtime.RedisSaver.from_conn_string")
    @patch("app.services.burt_runtime.BugAgentState", return_value=sentinel.initial_state)
    @patch(
        "app.services.burt_runtime.ingest_user_description",
        return_value={"messages": sentinel.initial_message_update},
    )
    @patch(
        "app.services.burt_runtime.load_bug_graph_context",
        return_value=("transitions", "Test App", "screen descriptions"),
    )
    @patch("app.services.burt_runtime.uuid4", return_value="session-123")
    def test_start_conversation_persists_completed_response(
        self,
        _mock_uuid4,
        _mock_load_bug_graph_context,
        _mock_ingest_user_description,
        _mock_bug_agent_state,
        mock_from_conn_string,
        mock_build_burt_graph,
        mock_create_runtime_context,
        mock_create_session_record,
        mock_flush_active_turn,
    ):
        runtime_context = self._runtime_context()
        mock_create_runtime_context.return_value = runtime_context
        # Simulate the RedisSaver context manager yielding a checkpointer instance.
        checkpointer = MagicMock()
        # Simulate the compiled graph returned by build_burt_graph(checkpointer).
        graph = MagicMock()
        # Returning full_report without __interrupt__ means the conversation is complete.
        graph.invoke.return_value = {
            "BugInfo": {"id": 42},
            "full_report": {"title": "Final report"},
        }
        mock_build_burt_graph.return_value = graph
        context_manager = MagicMock()
        context_manager.__enter__.return_value = checkpointer
        context_manager.__exit__.return_value = False
        mock_from_conn_string.return_value = context_manager

        response = burt_runtime.start_conversation(
            bug_id=42,
            user_description="initial bug description",
        )

        # The start flow should persist a completed response including the generated final report.
        self.assertEqual(response.session_id, "session-123")
        self.assertEqual(response.status, "completed")
        self.assertIsNone(response.question)
        self.assertEqual(response.final_report, {"title": "Final report"})
        mock_create_runtime_context.assert_called_once_with(
            session_id="session-123",
            log_path=Path("logs") / str(burt_runtime.config.PROMPT_VERSION) / "session-123.log",
            sink_mode="redis_then_file",
            redis_client=burt_runtime.redis_client,
        )
        mock_flush_active_turn.assert_called_once_with(runtime_context)
        self.assertEqual(checkpointer.setup.call_count, 2)
        runtime_context.sink.finalize_session.assert_called_once_with(
            session_id="session-123",
            final_report={"title": "Final report"},
            run_metadata={
                "bug_id": 42,
                "description_level": None,
                "input_source": "user",
                "runtime": "api",
            },
            revision=1,
        )
        mock_create_session_record.assert_called_once_with(
            {
                "session_id": "session-123",
                "bug_id": 42,
                "status": "completed",
                "question": None,
                "final_report": {"title": "Final report"},
                "draft_revision": 1,
                "final_revision": 0,
                "edits_remaining": 3,
            }
        )
        checkpointer.delete_thread.assert_called_once_with("session-123")


class ResumeConversationTests(unittest.TestCase):
    def _runtime_context(self):
        return SimpleNamespace(
            sink=MagicMock(),
            logger=SimpleNamespace(filepath=Path("logs/test.log")),
        )

    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime._flush_active_turn")
    @patch("app.services.burt_runtime.create_session_record")
    @patch(
        "app.services.burt_runtime.get_session",
        return_value={
            "session_id": "session-123",
            "bug_id": 42,
            "status": "awaiting_user",
            "question": "Old question",
            "final_report": None,
        },
    )
    @patch("app.services.burt_runtime.create_runtime_context")
    @patch("app.services.burt_runtime.build_burt_graph")
    @patch("app.services.burt_runtime.RedisSaver.from_conn_string")
    @patch("app.services.burt_runtime.Command", return_value=sentinel.resume_command)
    @patch(
        "app.services.burt_runtime.load_bug_graph_context",
        return_value=("transitions", "Test App", "screen descriptions"),
    )
    @patch(
        "app.services.burt_runtime.acquire_session_lock",
        return_value="owner-token",
    )
    def test_resume_conversation_uses_persisted_metadata_and_resume_command(
        self,
        mock_acquire_session_lock,
        mock_load_bug_graph_context,
        mock_command,
        mock_from_conn_string,
        mock_build_burt_graph,
        mock_create_runtime_context,
        mock_get_session,
        mock_create_session_record,
        mock_flush_active_turn,
        mock_release_session_lock,
    ):
        runtime_context = self._runtime_context()
        mock_create_runtime_context.return_value = runtime_context
        # Simulate the RedisSaver context manager yielding a checkpointer instance.
        checkpointer = MagicMock()
        # Simulate the compiled graph returned by build_burt_graph(checkpointer).
        graph = MagicMock()
        # Returning __interrupt__ means resume paused again and should persist the next follow-up question.
        graph.invoke.return_value = {
            "__interrupt__": [{"Follow Up Question": "What happened next?"}]
        }
        mock_build_burt_graph.return_value = graph
        context_manager = MagicMock()
        context_manager.__enter__.return_value = checkpointer
        context_manager.__exit__.return_value = False
        mock_from_conn_string.return_value = context_manager

        response = burt_runtime.resume_conversation(
            user_description="next message",
            session_id="session-123",
        )

        # Resume should rebuild runtime config from stored session metadata and invoke the graph with Command(resume=...).
        self.assertEqual(response.session_id, "session-123")
        self.assertEqual(response.status, "awaiting_user")
        self.assertEqual(response.question, "What happened next?")
        self.assertIsNone(response.final_report)
        mock_acquire_session_lock.assert_called_once_with("session-123")
        mock_get_session.assert_called_once_with("session-123")
        mock_load_bug_graph_context.assert_called_once_with(
            current_bug=42,
        )
        mock_create_runtime_context.assert_called_once_with(
            session_id="session-123",
            log_path=Path("logs") / str(burt_runtime.config.PROMPT_VERSION) / "session-123.log",
            sink_mode="redis_then_file",
            redis_client=burt_runtime.redis_client,
        )
        checkpointer.setup.assert_called_once_with()
        mock_build_burt_graph.assert_called_once_with(checkpointer)
        mock_command.assert_called_once_with(resume="next message")
        graph.invoke.assert_called_once_with(
            sentinel.resume_command,
            config={
                "configurable": {
                    "transitions": "transitions",
                    "app_name": "Test App",
                    "screen_descriptions": "screen descriptions",
                    "thread_id": "session-123",
                    "runtime_context": runtime_context,
                }
            },
        )
        mock_flush_active_turn.assert_called_once_with(runtime_context)
        runtime_context.sink.finalize_session.assert_not_called()
        checkpointer.delete_thread.assert_not_called()
        mock_create_session_record.assert_called_once_with(
            {
                "session_id": "session-123",
                "bug_id": 42,
                "status": "awaiting_user",
                "question": "What happened next?",
                "final_report": None,
                "draft_revision": 0,
                "final_revision": 0,
                "edits_remaining": 3,
            }
        )
        mock_release_session_lock.assert_called_once_with(
            "session-123",
            "owner-token",
        )

    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime._flush_active_turn")
    @patch("app.services.burt_runtime.create_session_record")
    @patch(
        "app.services.burt_runtime.get_session",
        return_value={
            "session_id": "session-123",
            "bug_id": 42,
            "status": "awaiting_user",
            "question": "Old question",
            "final_report": None,
        },
    )
    @patch("app.services.burt_runtime.create_runtime_context")
    @patch("app.services.burt_runtime.build_burt_graph")
    @patch("app.services.burt_runtime.RedisSaver.from_conn_string")
    @patch("app.services.burt_runtime.Command", return_value=sentinel.resume_command)
    @patch(
        "app.services.burt_runtime.load_bug_graph_context",
        return_value=("transitions", "Test App", "screen descriptions"),
    )
    @patch(
        "app.services.burt_runtime.acquire_session_lock",
        return_value="owner-token",
    )
    def test_resume_conversation_persists_completed_response(
        self,
        _mock_acquire_session_lock,
        _mock_load_bug_graph_context,
        _mock_command,
        mock_from_conn_string,
        mock_build_burt_graph,
        mock_create_runtime_context,
        _mock_get_session,
        mock_create_session_record,
        mock_flush_active_turn,
        mock_release_session_lock,
    ):
        runtime_context = self._runtime_context()
        mock_create_runtime_context.return_value = runtime_context
        # Simulate the RedisSaver context manager yielding a checkpointer instance.
        checkpointer = MagicMock()
        # Simulate the compiled graph returned by build_burt_graph(checkpointer).
        graph = MagicMock()
        # Returning full_report without __interrupt__ means resume finished the workflow.
        graph.invoke.return_value = {
            "BugInfo": {"id": 42},
            "full_report": {"title": "Final report"},
        }
        mock_build_burt_graph.return_value = graph
        context_manager = MagicMock()
        context_manager.__enter__.return_value = checkpointer
        context_manager.__exit__.return_value = False
        mock_from_conn_string.return_value = context_manager

        response = burt_runtime.resume_conversation(
            user_description="next message",
            session_id="session-123",
        )

        # A successful resume completion should persist the completed response and release the session lock.
        self.assertEqual(response.session_id, "session-123")
        self.assertEqual(response.status, "completed")
        self.assertIsNone(response.question)
        self.assertEqual(response.final_report, {"title": "Final report"})
        mock_create_runtime_context.assert_called_once_with(
            session_id="session-123",
            log_path=Path("logs") / str(burt_runtime.config.PROMPT_VERSION) / "session-123.log",
            sink_mode="redis_then_file",
            redis_client=burt_runtime.redis_client,
        )
        mock_flush_active_turn.assert_called_once_with(runtime_context)
        self.assertEqual(checkpointer.setup.call_count, 2)
        runtime_context.sink.finalize_session.assert_called_once_with(
            session_id="session-123",
            final_report={"title": "Final report"},
            run_metadata={
                "bug_id": 42,
                "description_level": None,
                "input_source": "user",
                "runtime": "api",
            },
            revision=1,
        )
        mock_create_session_record.assert_called_once_with(
            {
                "session_id": "session-123",
                "bug_id": 42,
                "status": "completed",
                "question": None,
                "final_report": {"title": "Final report"},
                "draft_revision": 1,
                "final_revision": 0,
                "edits_remaining": 3,
            }
        )
        checkpointer.delete_thread.assert_called_once_with("session-123")
        mock_release_session_lock.assert_called_once_with(
            "session-123",
            "owner-token",
        )

    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime.get_session", return_value=None)
    @patch(
        "app.services.burt_runtime.acquire_session_lock",
        return_value="owner-token",
    )
    def test_resume_conversation_raises_when_session_record_not_found(
        self,
        mock_acquire_session_lock,
        mock_get_session,
        mock_release_session_lock,
    ):
        # A missing persisted session record should fail fast with SessionNotFoundError.
        with self.assertRaises(burt_runtime.SessionNotFoundError):
            burt_runtime.resume_conversation(
                user_description="next message",
                session_id="session-123",
            )

        mock_acquire_session_lock.assert_called_once_with("session-123")
        mock_get_session.assert_called_once_with("session-123")
        # Even on validation failure, resume should still release the acquired session lock.
        mock_release_session_lock.assert_called_once_with(
            "session-123",
            "owner-token",
        )

    @patch("app.services.burt_runtime.release_session_lock")
    @patch(
        "app.services.burt_runtime.get_session",
        return_value={
            "session_id": "session-123",
            "bug_id": 42,
            "status": "completed",
            "question": None,
            "final_report": {"title": "Final report"},
        },
    )
    @patch(
        "app.services.burt_runtime.acquire_session_lock",
        return_value="owner-token",
    )
    def test_resume_conversation_raises_when_session_is_already_completed(
        self,
        mock_acquire_session_lock,
        mock_get_session,
        mock_release_session_lock,
    ):
        # A completed session should not be resumable.
        with self.assertRaises(burt_runtime.SessionCompletedError):
            burt_runtime.resume_conversation(
                user_description="next message",
                session_id="session-123",
            )

        mock_acquire_session_lock.assert_called_once_with("session-123")
        mock_get_session.assert_called_once_with("session-123")
        # The acquired lock should still be released when resume rejects a completed session.
        mock_release_session_lock.assert_called_once_with(
            "session-123",
            "owner-token",
        )

    @patch("app.services.burt_runtime.release_session_lock")
    @patch(
        "app.services.burt_runtime.get_session",
        return_value={
            "session_id": "session-123",
            "bug_id": "42",
            "status": "awaiting_user",
            "question": "Old question",
            "final_report": None,
        },
    )
    @patch(
        "app.services.burt_runtime.acquire_session_lock",
        return_value="owner-token",
    )
    def test_resume_conversation_raises_when_session_record_is_malformed(
        self,
        mock_acquire_session_lock,
        mock_get_session,
        mock_release_session_lock,
    ):
        # Resume requires an int bug_id in the persisted session metadata.
        with self.assertRaises(burt_runtime.InvalidSessionError):
            burt_runtime.resume_conversation(
                user_description="next message",
                session_id="session-123",
            )

        mock_acquire_session_lock.assert_called_once_with("session-123")
        mock_get_session.assert_called_once_with("session-123")
        # The acquired lock should still be released when persisted metadata is malformed.
        mock_release_session_lock.assert_called_once_with(
            "session-123",
            "owner-token",
        )

    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime._flush_active_turn")
    @patch("app.services.burt_runtime.create_session_record")
    @patch(
        "app.services.burt_runtime.get_session",
        return_value={
            "session_id": "session-123",
            "bug_id": 42,
            "status": "awaiting_user",
            "question": "Old question",
            "final_report": None,
        },
    )
    @patch("app.services.burt_runtime.create_runtime_context")
    @patch("app.services.burt_runtime.build_burt_graph")
    @patch("app.services.burt_runtime.RedisSaver.from_conn_string")
    @patch("app.services.burt_runtime.Command", return_value=sentinel.resume_command)
    @patch(
        "app.services.burt_runtime.load_bug_graph_context",
        return_value=("transitions", "Test App", "screen descriptions"),
    )
    @patch(
        "app.services.burt_runtime.acquire_session_lock",
        return_value="owner-token",
    )
    def test_resume_conversation_allows_sessions_without_description_level(
        self,
        _mock_acquire_session_lock,
        _mock_load_bug_graph_context,
        _mock_command,
        mock_from_conn_string,
        mock_build_burt_graph,
        mock_create_runtime_context,
        _mock_get_session,
        mock_create_session_record,
        mock_flush_active_turn,
        mock_release_session_lock,
    ):
        runtime_context = self._runtime_context()
        mock_create_runtime_context.return_value = runtime_context
        checkpointer = MagicMock()
        graph = MagicMock()
        graph.invoke.return_value = {
            "__interrupt__": [{"Follow Up Question": "What happened next?"}]
        }
        mock_build_burt_graph.return_value = graph
        context_manager = MagicMock()
        context_manager.__enter__.return_value = checkpointer
        context_manager.__exit__.return_value = False
        mock_from_conn_string.return_value = context_manager

        response = burt_runtime.resume_conversation(
            user_description="next message",
            session_id="session-123",
        )

        self.assertEqual(response.status, "awaiting_user")
        mock_create_runtime_context.assert_called_once_with(
            session_id="session-123",
            log_path=Path("logs") / str(burt_runtime.config.PROMPT_VERSION) / "session-123.log",
            sink_mode="redis_then_file",
            redis_client=burt_runtime.redis_client,
        )
        mock_create_session_record.assert_called_once_with(
            {
                "session_id": "session-123",
                "bug_id": 42,
                "status": "awaiting_user",
                "question": "What happened next?",
                "final_report": None,
                "draft_revision": 0,
                "final_revision": 0,
                "edits_remaining": 3,
            }
        )
        mock_flush_active_turn.assert_called_once_with(runtime_context)
        mock_release_session_lock.assert_called_once_with("session-123", "owner-token")


def _completed_session_record(**overrides):
    """Build the persisted record of a session whose first draft report is ready."""
    return {
        "session_id": "session-123",
        "bug_id": 42,
        "status": "completed",
        "question": None,
        "final_report": {"title": "Draft report"},
        "draft_revision": 1,
        "final_revision": 0,
        "edits_remaining": 3,
        **overrides,
    }


class SaveModifiedReportTests(unittest.TestCase):
    def _runtime_context(self):
        return SimpleNamespace(
            sink=MagicMock(),
            logger=SimpleNamespace(filepath=Path("logs/test.log")),
        )

    def _patch_regeneration_run(self, graph_result):
        """Patch out everything the regeneration run touches beyond the log file."""
        checkpointer = MagicMock()
        graph = MagicMock()
        graph.invoke.return_value = graph_result
        context_manager = MagicMock()
        context_manager.__enter__.return_value = checkpointer
        context_manager.__exit__.return_value = False

        patches = {
            "load_bug_graph_context": patch(
                "app.services.burt_runtime.load_bug_graph_context",
                return_value=("transitions", "Test App", "screen descriptions"),
            ),
            "create_runtime_context": patch(
                "app.services.burt_runtime.create_runtime_context",
                return_value=self._runtime_context(),
            ),
            "ingest_user_description": patch(
                "app.services.burt_runtime.ingest_user_description",
                return_value={"messages": sentinel.initial_message_update},
            ),
            "bug_agent_state": patch(
                "app.services.burt_runtime.BugAgentState",
                return_value=sentinel.initial_state,
            ),
            "from_conn_string": patch(
                "app.services.burt_runtime.RedisSaver.from_conn_string",
                return_value=context_manager,
            ),
            "build_burt_graph": patch(
                "app.services.burt_runtime.build_burt_graph",
                return_value=graph,
            ),
            "flush_active_turn": patch("app.services.burt_runtime._flush_active_turn"),
        }

        started = {name: patcher.start() for name, patcher in patches.items()}
        for patcher in patches.values():
            self.addCleanup(patcher.stop)

        return started, checkpointer, graph

    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime.acquire_session_lock", return_value="owner-token")
    @patch("app.services.burt_runtime.create_session_record")
    @patch(
        "app.services.burt_runtime.get_session",
        return_value=_completed_session_record(),
    )
    def test_save_modified_report_logs_the_edit_then_regenerates_the_next_draft(
        self,
        mock_get_session,
        mock_create_session_record,
        _mock_acquire_session_lock,
        mock_release_session_lock,
    ):
        started, checkpointer, graph = self._patch_regeneration_run(
            {"BugInfo": {"id": 42}, "full_report": {"title": "Regenerated report"}},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "session-123.log"

            with patch(
                "app.services.burt_runtime.build_api_log_path",
                return_value=log_path,
            ):
                response = burt_runtime.save_modified_report(
                    session_id="session-123",
                    modified_report={"title": "Edited report"},
                )

            log_text = log_path.read_text()

        # The saved edit is banked as final report 1 before the rerun starts.
        self.assertIn('"record_type": "modified_report"', log_text)
        self.assertIn('"revision": 1', log_text)
        mock_get_session.assert_called_once_with("session-123")

        # The rerun re-enters the graph the way a typed message does, seeded with
        # the edited report rather than with a resume command.
        started["ingest_user_description"].assert_called_once()
        seeded_description = started["ingest_user_description"].call_args.args[0]
        self.assertIn("Edited report", seeded_description)
        graph.invoke.assert_called_once_with(
            sentinel.initial_state,
            config={
                "configurable": {
                    "transitions": "transitions",
                    "app_name": "Test App",
                    "screen_descriptions": "screen descriptions",
                    "thread_id": "session-123",
                    "runtime_context": started["create_runtime_context"].return_value,
                }
            },
        )
        # Any checkpoint the previous run left behind would resume it instead.
        checkpointer.delete_thread.assert_any_call("session-123")

        # The response carries the regenerated draft report 2, with two edits left.
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.final_report, {"title": "Regenerated report"})
        self.assertEqual(response.draft_revision, 2)
        self.assertEqual(response.final_revision, 1)
        self.assertEqual(response.edits_remaining, 2)
        started["create_runtime_context"].return_value.sink.finalize_session.assert_called_once_with(
            session_id="session-123",
            final_report={"title": "Regenerated report"},
            run_metadata={
                "bug_id": 42,
                "description_level": None,
                "input_source": "user",
                "runtime": "api",
            },
            revision=2,
        )
        self.assertEqual(
            mock_create_session_record.call_args_list[-1].args[0],
            {
                "session_id": "session-123",
                "bug_id": 42,
                "status": "completed",
                "question": None,
                "final_report": {"title": "Regenerated report"},
                "draft_revision": 2,
                "final_revision": 1,
                "edits_remaining": 2,
            },
        )
        mock_release_session_lock.assert_called_once_with("session-123", "owner-token")

    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime.acquire_session_lock", return_value="owner-token")
    @patch("app.services.burt_runtime.create_session_record")
    @patch(
        "app.services.burt_runtime.get_session",
        return_value=_completed_session_record(),
    )
    def test_save_modified_report_runs_the_regeneration_in_a_single_pass(
        self,
        _mock_get_session,
        _mock_create_session_record,
        _mock_acquire_session_lock,
        _mock_release_session_lock,
    ):
        started, _checkpointer, _graph = self._patch_regeneration_run(
            {"BugInfo": {"id": 42}, "full_report": {"title": "Regenerated report"}},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "app.services.burt_runtime.build_api_log_path",
                return_value=Path(tmpdir) / "session-123.log",
            ):
                burt_runtime.save_modified_report(
                    session_id="session-123",
                    modified_report={"title": "Edited report"},
                )

        # The user has already said what they wanted changed, so the run is seeded
        # to regenerate in one try rather than to ask anything back.
        started["bug_agent_state"].assert_called_once_with(
            messages=[sentinel.initial_message_update],
            single_pass=True,
        )

    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime.acquire_session_lock", return_value="owner-token")
    @patch(
        "app.services.burt_runtime.get_session",
        return_value=_completed_session_record(final_revision=3, draft_revision=4),
    )
    def test_save_modified_report_stops_after_the_configured_edit_limit(
        self,
        mock_get_session,
        _mock_acquire_session_lock,
        mock_release_session_lock,
    ):
        with self.assertRaises(burt_runtime.ReportEditLimitError):
            burt_runtime.save_modified_report(
                session_id="session-123",
                modified_report={"title": "Edited report"},
            )

        mock_get_session.assert_called_once_with("session-123")
        mock_release_session_lock.assert_called_once_with("session-123", "owner-token")

    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime.acquire_session_lock", return_value="owner-token")
    @patch("app.services.burt_runtime.get_session", return_value=None)
    def test_save_modified_report_raises_when_session_missing(
        self,
        mock_get_session,
        _mock_acquire_session_lock,
        mock_release_session_lock,
    ):
        with self.assertRaises(burt_runtime.SessionNotFoundError):
            burt_runtime.save_modified_report(
                session_id="missing-session",
                modified_report={"title": "Edited report"},
            )

        mock_get_session.assert_called_once_with("missing-session")
        mock_release_session_lock.assert_called_once_with(
            "missing-session",
            "owner-token",
        )

    @patch("app.services.burt_runtime.acquire_session_lock", return_value=None)
    def test_save_modified_report_refuses_while_the_session_is_busy(
        self,
        mock_acquire_session_lock,
    ):
        # The rerun invokes the graph, so it cannot race a resume on the same session.
        with self.assertRaises(burt_runtime.SessionLockedError):
            burt_runtime.save_modified_report(
                session_id="session-123",
                modified_report={"title": "Edited report"},
            )

        mock_acquire_session_lock.assert_called_once_with("session-123")


class FormatReportAsDescriptionTests(unittest.TestCase):
    def test_flattens_every_report_field_into_labelled_prose(self):
        description = burt_runtime.format_report_as_description(
            {
                "title": "Crash on save",
                "steps_to_reproduce": ["Open the app.", "Tap Save."],
                "extra_metadata": {"severity": "high"},
            }
        )

        self.assertIn("Title: Crash on save", description)
        self.assertIn("Steps To Reproduce:\n- Open the app.\n- Tap Save.", description)
        self.assertIn('Extra Metadata: {"severity": "high"}', description)
        # The agent has to read this as a bug description, not as a report to copy.
        self.assertTrue(description.startswith("I corrected the bug report"))


if __name__ == "__main__":
    unittest.main()
