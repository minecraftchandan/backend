import json
import os
import unittest
from io import BytesIO
from urllib.error import HTTPError
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

    def test_resend_rejection_includes_provider_reason_without_exposing_key(self):
        response_body = json.dumps({
            "name": "validation_error",
            "message": "You can only send testing emails to your own email address.",
        }).encode("utf-8")
        error = HTTPError(
            "https://api.resend.com/emails",
            403,
            "Forbidden",
            {},
            BytesIO(response_body),
        )
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test-api-key",
            "RESEND_FROM_EMAIL": "onboarding@resend.dev",
        }), patch(
            "app.services.email.resend.urlopen",
            side_effect=error,
        ):
            with self.assertRaises(EmailDeliveryError) as raised:
                send_inspector_credentials_email(
                    "inspector@example.com",
                    "Priya Sharma",
                    "priya.sharma",
                    "TempPass123",
                )

        self.assertIn("HTTP 403", str(raised.exception))
        self.assertIn("own email address", str(raised.exception))
        self.assertNotIn("test-api-key", str(raised.exception))

    def test_resend_rejection_logs_request_reference_and_nested_message(self):
        response_body = json.dumps({
            "error": {"message": "The sender domain has not been verified."},
        }).encode("utf-8")
        error = HTTPError(
            "https://api.resend.com/emails",
            403,
            "Forbidden",
            {"x-resend-id": "req_test_123"},
            BytesIO(response_body),
        )
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test-api-key",
            "RESEND_FROM_EMAIL": "accounts@example.com",
        }), patch(
            "app.services.email.resend.urlopen",
            side_effect=error,
        ), self.assertLogs("app.services.email.resend", level="WARNING") as logs:
            with self.assertRaises(EmailDeliveryError) as raised:
                send_inspector_credentials_email(
                    "inspector@example.com",
                    "Priya Sharma",
                    "priya.sharma",
                    "TempPass123",
                )

        self.assertIn("sender domain has not been verified", str(raised.exception))
        self.assertIn("req_test_123", str(raised.exception))
        self.assertIn("req_test_123", logs.output[0])
        self.assertNotIn("inspector@example.com", logs.output[0])
        self.assertNotIn("test-api-key", logs.output[0])

    def test_resend_rejection_logs_metadata_for_empty_gateway_response(self):
        error = HTTPError(
            "https://api.resend.com/emails",
            403,
            "Forbidden",
            {
                "Content-Type": "text/html",
                "Server": "example-gateway",
                "cf-ray": "gateway-request-123",
            },
            BytesIO(b""),
        )
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test-api-key",
            "RESEND_FROM_EMAIL": "accounts@example.com",
        }), patch(
            "app.services.email.resend.urlopen",
            side_effect=error,
        ), self.assertLogs("app.services.email.resend", level="WARNING") as logs:
            with self.assertRaises(EmailDeliveryError):
                send_inspector_credentials_email(
                    "inspector@example.com",
                    "Priya Sharma",
                    "priya.sharma",
                    "TempPass123",
                )

        self.assertIn("response_format=empty-or-unreadable", logs.output[0])
        self.assertIn("response_content_type=text/html", logs.output[0])
        self.assertIn("response_server=example-gateway", logs.output[0])
        self.assertIn("gateway_request_id=gateway-request-123", logs.output[0])
        self.assertNotIn("inspector@example.com", logs.output[0])
        self.assertNotIn("test-api-key", logs.output[0])


if __name__ == "__main__":
    unittest.main()
