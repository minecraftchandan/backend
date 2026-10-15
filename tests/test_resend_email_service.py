import json
import os
import unittest
from unittest.mock import Mock, patch

from app.services.email.resend import (
    EmailDeliveryError,
    send_inspector_credentials_email,
)


class ResendEmailServiceTests(unittest.TestCase):
    def test_sends_professional_credentials_email_through_resend(self):
        response = Mock()
        response.status = 200
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test-api-key",
            "RESEND_FROM_EMAIL": "accounts@example.com",
            "RESEND_FROM_NAME": "Satark Drishti",
        }), patch("app.services.email.resend.urlopen", return_value=response) as urlopen:
            send_inspector_credentials_email(
                recipient="inspector@example.com",
                name="Priya <Sharma>",
                username="priya.sharma",
                password="Temp&Pass123",
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-api-key")
        self.assertEqual(payload["to"], ["inspector@example.com"])
        self.assertEqual(payload["from"], "Satark Drishti <accounts@example.com>")
        self.assertIn("priya.sharma", payload["text"])
        self.assertIn("Temp&Pass123", payload["text"])
        self.assertIn("Priya &lt;Sharma&gt;", payload["html"])
        self.assertIn("Temp&amp;Pass123", payload["html"])

    def test_missing_resend_configuration_is_reported(self):
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "",
            "RESEND_FROM_EMAIL": "",
        }):
            with self.assertRaises(EmailDeliveryError) as raised:
                send_inspector_credentials_email(
                    "inspector@example.com",
                    "Priya Sharma",
                    "priya.sharma",
                    "TempPass123",
                )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("RESEND_API_KEY", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
