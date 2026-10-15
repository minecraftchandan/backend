import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api import security


class UserAccessTokenTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"API_ACCESS_TOKEN": "s" * 40})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_issue_and_verify_user_token(self):
        token, expires_at = security.issue_user_access_token("inspector", "inspector")

        claims = security.verify_user_access_token(token)

        self.assertEqual(claims["sub"], "inspector")
        self.assertEqual(claims["role"], "inspector")
        self.assertEqual(claims["exp"], expires_at)

    def test_rejects_modified_token(self):
        token, _ = security.issue_user_access_token("authority", "authority")
        segments = token.split(".")
        segments[1] = ("A" if segments[1][0] != "A" else "B") + segments[1][1:]

        with self.assertRaises(HTTPException) as raised:
            security.verify_user_access_token(".".join(segments))

        self.assertEqual(raised.exception.status_code, 401)

    def test_rejects_malformed_token(self):
        with self.assertRaises(HTTPException) as raised:
            security.verify_user_access_token("not-a-token")

        self.assertEqual(raised.exception.status_code, 401)

    def test_rejects_expired_token(self):
        token, _ = security.issue_user_access_token("authority", "authority")
        with patch.object(security.time, "time", return_value=10**12):
            with self.assertRaises(HTTPException) as raised:
                security.verify_user_access_token(token)

        self.assertEqual(raised.exception.status_code, 401)

    def test_requires_configured_signing_secret(self):
        with patch.dict(os.environ, {"API_ACCESS_TOKEN": ""}):
            with self.assertRaises(HTTPException) as raised:
                security.issue_user_access_token("authority", "authority")

        self.assertEqual(raised.exception.status_code, 503)

    def test_pending_inspector_can_read_but_cannot_write(self):
        token, _ = security.issue_user_access_token("inspector", "inspector", user_id=12)
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = {
            "status": "Pending",
            "active": True,
        }
        database = MagicMock()
        database.__enter__.return_value = connection

        with patch("app.database.get_connection", return_value=database):
            with self.assertRaises(HTTPException) as raised:
                security.require_api_access(
                    SimpleNamespace(method="POST", client=SimpleNamespace(host="203.0.113.1")),
                    credentials,
                )

            self.assertEqual(raised.exception.status_code, 403)
            self.assertIn("Manual verification", raised.exception.detail)

            security.require_api_access(
                SimpleNamespace(method="GET", client=SimpleNamespace(host="203.0.113.1")),
                credentials,
            )

        connection.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
