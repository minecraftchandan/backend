import os
import unittest
from unittest.mock import patch

from app.api import security
from app.api.routes.auth import LoginRequest, login


class LoginRouteTests(unittest.TestCase):
    def test_successful_login_returns_a_signed_access_token(self):
        with patch.dict(os.environ, {"API_ACCESS_TOKEN": "s" * 40}):
            with patch(
                "app.api.routes.auth.authenticate",
                return_value={
                    "role": "inspector",
                    "username": "inspector",
                    "displayName": "Field Inspector",
                },
            ):
                result = login(LoginRequest(
                    username="inspector",
                    password="password",
                    portal_role="Inspector",
                ))
                claims = security.verify_user_access_token(result["accessToken"])
        self.assertEqual(result["tokenType"], "Bearer")
        self.assertGreater(result["expiresAt"], 0)
        self.assertEqual(claims["sub"], "inspector")
        self.assertEqual(claims["role"], "inspector")


if __name__ == "__main__":
    unittest.main()
