import unittest
from unittest.mock import MagicMock, patch, sentinel

from app.services import burt_runtime


class StartConversationTests(unittest.TestCase):
    @patch("app.services.burt_runtime.create_session_record")
    @patch("app.services.burt_runtime.create_runtime_context", return_value=sentinel.runtime_context)
    @patch("app.services.burt_runtime.build_burt_graph")
    @patch("app.services.burt_runtime.RedisSaver.from_conn_string")
    @patch("app.services.burt_runtime.BugAgentState", return_value=sentinel.initial_state)
    @patch(
        "app.services.burt_runtime.ingest_user_description",
        return_value={"messages": sentinel.initial_message_update},
    )
    @patch(
        "app.services.burt_runtime.load_bug_graph_context",
        return_value=("app graph", "Test App", "screen descriptions"),
    )
    @patch(
        "app.services.burt_runtime.load_initial_message",
        return_value="initial bug description",
    )
    @patch("app.services.burt_runtime.uuid4", return_value="session-123")
    def test_start_conversation_persists_interrupt_response(
        self,
        mock_uuid4,
        mock_load_initial_message,
        mock_load_bug_graph_context,
        mock_ingest_user_description,
        mock_bug_agent_state,
        mock_from_conn_string,
        mock_build_burt_graph,
        mock_create_runtime_context,
        mock_create_session_record,
    ):
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

        response = burt_runtime.start_conversation(bug_id=42, description_level="LC_LP")

        # The start flow should persist an awaiting_user response tied to the generated session id.
        self.assertEqual(response.session_id, "session-123")
        self.assertEqual(response.status, "awaiting_user")
        self.assertEqual(response.question, "What screen were you on?")
        self.assertIsNone(response.final_report)
        mock_load_initial_message.assert_called_once_with(
            current_bug=42,
            description_level="LC_LP",
        )
        mock_load_bug_graph_context.assert_called_once_with(
            current_bug=42,
            description_level="LC_LP",
        )
        mock_create_runtime_context.assert_called_once_with(
            session_id="session-123",
            bug_id=42,
            description_level="LC_LP",
        )
        mock_ingest_user_description.assert_called_once_with(
            "initial bug description",
            runtime_context=sentinel.runtime_context,
        )
        mock_bug_agent_state.assert_called_once_with(
            messages=[sentinel.initial_message_update]
        )
        checkpointer.setup.assert_called_once_with()
        mock_build_burt_graph.assert_called_once_with(checkpointer)
        graph.invoke.assert_called_once_with(
            sentinel.initial_state,
            config={
                "configurable": {
                    "app_graph": "app graph",
                    "app_name": "Test App",
                    "screen_descriptions": "screen descriptions",
                    "thread_id": "session-123",
                    "runtime_context": sentinel.runtime_context,
                }
            },
        )
        mock_create_session_record.assert_called_once_with(
            {
                "session_id": "session-123",
                "bug_id": 42,
                "description_level": "LC_LP",
                "status": "awaiting_user",
                "question": "What screen were you on?",
                "final_report": None,
            }
        )
        mock_uuid4.assert_called_once_with()

    @patch("app.services.burt_runtime.create_session_record")
    @patch("app.services.burt_runtime.create_runtime_context", return_value=sentinel.runtime_context)
    @patch(
        "app.services.burt_runtime.gen_report",
        return_value={"title": "Final report"},
    )
    @patch("app.services.burt_runtime.build_burt_graph")
    @patch("app.services.burt_runtime.RedisSaver.from_conn_string")
    @patch("app.services.burt_runtime.BugAgentState", return_value=sentinel.initial_state)
    @patch(
        "app.services.burt_runtime.ingest_user_description",
        return_value={"messages": sentinel.initial_message_update},
    )
    @patch(
        "app.services.burt_runtime.load_bug_graph_context",
        return_value=("app graph", "Test App", "screen descriptions"),
    )
    @patch(
        "app.services.burt_runtime.load_initial_message",
        return_value="initial bug description",
    )
    @patch("app.services.burt_runtime.uuid4", return_value="session-123")
    def test_start_conversation_persists_completed_response(
        self,
        _mock_uuid4,
        _mock_load_initial_message,
        _mock_load_bug_graph_context,
        _mock_ingest_user_description,
        _mock_bug_agent_state,
        mock_from_conn_string,
        mock_build_burt_graph,
        mock_gen_report,
        mock_create_runtime_context,
        mock_create_session_record,
    ):
        # Simulate the RedisSaver context manager yielding a checkpointer instance.
        checkpointer = MagicMock()
        # Simulate the compiled graph returned by build_burt_graph(checkpointer).
        graph = MagicMock()
        # Returning BugInfo without __interrupt__ means the conversation is complete and should generate a report.
        graph.invoke.return_value = {"BugInfo": {"id": 42}}
        mock_build_burt_graph.return_value = graph
        context_manager = MagicMock()
        context_manager.__enter__.return_value = checkpointer
        context_manager.__exit__.return_value = False
        mock_from_conn_string.return_value = context_manager

        response = burt_runtime.start_conversation(bug_id=42, description_level="LC_LP")

        # The start flow should persist a completed response including the generated final report.
        self.assertEqual(response.session_id, "session-123")
        self.assertEqual(response.status, "completed")
        self.assertIsNone(response.question)
        self.assertEqual(response.final_report, {"title": "Final report"})
        mock_create_runtime_context.assert_called_once_with(
            session_id="session-123",
            bug_id=42,
            description_level="LC_LP",
        )
        mock_gen_report.assert_called_once_with(
            {"id": 42},
            app_graph="app graph",
            app_name="Test App",
            runtime_context=sentinel.runtime_context,
        )
        mock_create_session_record.assert_called_once_with(
            {
                "session_id": "session-123",
                "bug_id": 42,
                "description_level": "LC_LP",
                "status": "completed",
                "question": None,
                "final_report": {"title": "Final report"},
            }
        )


class ResumeConversationTests(unittest.TestCase):
    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime.create_session_record")
    @patch(
        "app.services.burt_runtime.get_session",
        return_value={
            "session_id": "session-123",
            "bug_id": 42,
            "description_level": "LC_LP",
            "status": "awaiting_user",
            "question": "Old question",
            "final_report": None,
        },
    )
    @patch("app.services.burt_runtime.create_runtime_context", return_value=sentinel.runtime_context)
    @patch("app.services.burt_runtime.build_burt_graph")
    @patch("app.services.burt_runtime.RedisSaver.from_conn_string")
    @patch("app.services.burt_runtime.Command", return_value=sentinel.resume_command)
    @patch(
        "app.services.burt_runtime.load_bug_graph_context",
        return_value=("app graph", "Test App", "screen descriptions"),
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
        mock_release_session_lock,
    ):
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
            description_level="LC_LP",
        )
        mock_create_runtime_context.assert_called_once_with(
            session_id="session-123",
            bug_id=42,
            description_level="LC_LP",
        )
        checkpointer.setup.assert_called_once_with()
        mock_build_burt_graph.assert_called_once_with(checkpointer)
        mock_command.assert_called_once_with(resume="next message")
        graph.invoke.assert_called_once_with(
            sentinel.resume_command,
            config={
                "configurable": {
                    "app_graph": "app graph",
                    "app_name": "Test App",
                    "screen_descriptions": "screen descriptions",
                    "thread_id": "session-123",
                    "runtime_context": sentinel.runtime_context,
                }
            },
        )
        mock_create_session_record.assert_called_once_with(
            {
                "session_id": "session-123",
                "bug_id": 42,
                "description_level": "LC_LP",
                "status": "awaiting_user",
                "question": "What happened next?",
                "final_report": None,
            }
        )
        mock_release_session_lock.assert_called_once_with(
            "session-123",
            "owner-token",
        )

    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime.create_session_record")
    @patch(
        "app.services.burt_runtime.gen_report",
        return_value={"title": "Final report"},
    )
    @patch(
        "app.services.burt_runtime.get_session",
        return_value={
            "session_id": "session-123",
            "bug_id": 42,
            "description_level": "LC_LP",
            "status": "awaiting_user",
            "question": "Old question",
            "final_report": None,
        },
    )
    @patch("app.services.burt_runtime.create_runtime_context", return_value=sentinel.runtime_context)
    @patch("app.services.burt_runtime.build_burt_graph")
    @patch("app.services.burt_runtime.RedisSaver.from_conn_string")
    @patch("app.services.burt_runtime.Command", return_value=sentinel.resume_command)
    @patch(
        "app.services.burt_runtime.load_bug_graph_context",
        return_value=("app graph", "Test App", "screen descriptions"),
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
        mock_gen_report,
        mock_create_session_record,
        mock_release_session_lock,
    ):
        # Simulate the RedisSaver context manager yielding a checkpointer instance.
        checkpointer = MagicMock()
        # Simulate the compiled graph returned by build_burt_graph(checkpointer).
        graph = MagicMock()
        # Returning BugInfo without __interrupt__ means resume finished the workflow and should generate a report.
        graph.invoke.return_value = {"BugInfo": {"id": 42}}
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
            bug_id=42,
            description_level="LC_LP",
        )
        mock_gen_report.assert_called_once_with(
            {"id": 42},
            app_graph="app graph",
            app_name="Test App",
            runtime_context=sentinel.runtime_context,
        )
        mock_create_session_record.assert_called_once_with(
            {
                "session_id": "session-123",
                "bug_id": 42,
                "description_level": "LC_LP",
                "status": "completed",
                "question": None,
                "final_report": {"title": "Final report"},
            }
        )
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
            "description_level": "LC_LP",
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
            "description_level": None,
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
        # Resume requires an int bug_id and string description_level in the persisted session metadata.
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


if __name__ == "__main__":
    unittest.main()
