import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware

import config
from app.main import app
from app.services import burt_runtime, session_store


class CorsConfigTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_parse_cors_allowed_origins_defaults_to_local_vite_origin(self):
        self.assertEqual(
            config._parse_cors_allowed_origins(None),
            ["http://localhost:5173"],
        )

    def test_parse_cors_allowed_origins_trims_csv_values(self):
        self.assertEqual(
            config._parse_cors_allowed_origins(
                " http://localhost:5173, https://app.example.com  ,"
            ),
            ["http://localhost:5173", "https://app.example.com"],
        )


class SessionStoreLockTests(unittest.TestCase):
    @patch.object(session_store.redis_client, "set", return_value=True)
    def test_acquire_session_lock_returns_token_when_free(self, mock_set):
        # Verifies that a free session lock is acquired and returns an owner token.
        token = session_store.acquire_session_lock("session-123")

        self.assertIsInstance(token, str)
        self.assertTrue(token)
        mock_set.assert_called_once_with(
            "burt:session-lock:session-123",
            token,
            nx=True,
            ex=session_store.SESSION_LOCK_TTL_SECONDS,
        )

    @patch.object(session_store.redis_client, "set", return_value=False)
    def test_acquire_session_lock_returns_none_when_already_held(self, mock_set):
        # Verifies that lock acquisition fails cleanly when another worker already holds the lock.
        token = session_store.acquire_session_lock("session-123")

        self.assertIsNone(token)
        mock_set.assert_called_once()


class ResumeConversationLockTests(unittest.TestCase):
    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime.acquire_session_lock", return_value=None)
    def test_resume_conversation_raises_when_session_is_locked(
        self,
        mock_acquire,
        mock_release,
    ):
        # Verifies that resume_conversation fails fast when the per-session lock cannot be acquired.
        with self.assertRaises(burt_runtime.SessionLockedError):
            burt_runtime.resume_conversation("next message", "session-123")

        mock_acquire.assert_called_once_with("session-123")
        mock_release.assert_not_called()

    @patch("app.services.burt_runtime.release_session_lock")
    @patch("app.services.burt_runtime.get_session", return_value=None)
    @patch("app.services.burt_runtime.acquire_session_lock", return_value="owner-token")
    def test_resume_conversation_releases_lock_when_validation_fails(
        self,
        mock_acquire,
        mock_get_session,
        mock_release,
    ):
        # Verifies that the finally block still releases the lock when resume validation raises early.
        with self.assertRaises(burt_runtime.SessionNotFoundError):
            burt_runtime.resume_conversation("next message", "session-123")

        mock_acquire.assert_called_once_with("session-123")
        mock_get_session.assert_called_once_with("session-123")
        mock_release.assert_called_once_with("session-123", "owner-token")


class SessionRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_app_installs_cors_middleware(self):
        self.assertTrue(
            any(middleware.cls is CORSMiddleware for middleware in app.user_middleware)
        )

    @patch(
        "app.api.routes.sessions.start_conversation",
        return_value=burt_runtime.ConversationTurnResponse(
            session_id="session-123",
            status="awaiting_user",
            question="What screen were you on?",
            final_report=None,
        ),
    )
    def test_create_session_uses_user_description_payload(self, mock_start):
        response = self.client.post(
            "/sessions",
            json={"bug_id": 10, "user_description": "The app crashed after save."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "session_id": "session-123",
                "status": "awaiting_user",
                "question": "What screen were you on?",
                "final_report": None,
            },
        )
        mock_start.assert_called_once_with(
            bug_id=10,
            user_description="The app crashed after save.",
        )

    @patch("app.api.routes.sessions.list_active_bug_ids", return_value=[2, 10, 135])
    def test_active_bugs_returns_sorted_bug_ids(self, mock_list_active_bug_ids):
        response = self.client.get("/bugs/active")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"bug_ids": [2, 10, 135]})
        mock_list_active_bug_ids.assert_called_once_with()

    def test_cors_allows_the_local_vite_origin(self):
        response = self.client.get(
            "/healthz",
            headers={"Origin": "http://localhost:5173"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )

    def test_cors_preflight_succeeds_for_allowed_origin(self):
        response = self.client.options(
            "/sessions",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )

    def test_cors_does_not_allow_unlisted_origin(self):
        response = self.client.get(
            "/healthz",
            headers={"Origin": "http://localhost:4173"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    @patch(
        "app.api.routes.sessions.resume_conversation",
        side_effect=burt_runtime.SessionLockedError(
            "Session is already being resumed. Retry shortly."
        ),
    )
    def test_resume_session_maps_session_lock_to_conflict(self, mock_resume):
        # Verifies that the API translates service-level session lock contention into HTTP 409.
        response = self.client.post(
            "/sessions/session-123/messages",
            json={"user_description": "next message"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"detail": "Session is already being resumed. Retry shortly."},
        )
        mock_resume.assert_called_once_with(
            user_description="next message",
            session_id="session-123",
        )


if __name__ == "__main__":
    unittest.main()
