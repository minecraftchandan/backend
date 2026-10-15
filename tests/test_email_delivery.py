import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from app.services.email import delivery
from app.services.email.resend import EmailDeliveryError


class QueryResult:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self.row


class DeliveryDatabase:
    def __init__(self, claimed):
        self.claimed = claimed
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if "RETURNING id, name, email, username, temp_password" in query:
            return QueryResult(self.claimed)
        return QueryResult(rowcount=1)


class EmailDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.claimed = {
            "id": 12,
            "name": "Priya Sharma",
            "email": "priya.sharma@example.com",
            "username": "priya.sharma",
            "temp_password": "Temporary@123",
            "credentials_email_claimed_at": datetime.now(timezone.utc),
        }
        self.database = DeliveryDatabase(self.claimed)

    def patch_database(self):
        @contextmanager
        def connection():
            yield self.database

        return patch("app.services.email.delivery.get_connection", side_effect=connection)

    def test_successful_delivery_records_sent_state_and_claims_before_sending(self):
        with self.patch_database(), patch(
            "app.services.email.delivery.send_inspector_credentials_email"
        ) as send_email:
            delivered = delivery.deliver_inspector_credentials_email(12)

        self.assertTrue(delivered)
        send_email.assert_called_once_with(
            recipient="priya.sharma@example.com",
            name="Priya Sharma",
            username="priya.sharma",
            password="Temporary@123",
        )
        self.assertEqual(len(self.database.queries), 2)
        self.assertIn("credentials_email_claimed_at = clock_timestamp()", self.database.queries[0][0])
        self.assertIn("credentials_email_sent_at = CURRENT_TIMESTAMP", self.database.queries[1][0])

    def test_provider_failure_clears_claim_and_persists_error_for_retry(self):
        with self.patch_database(), patch(
            "app.services.email.delivery.send_inspector_credentials_email",
            side_effect=EmailDeliveryError("Resend did not accept the email."),
        ):
            with self.assertRaises(EmailDeliveryError):
                delivery.deliver_inspector_credentials_email(12)

        self.assertEqual(len(self.database.queries), 2)
        self.assertIn("credentials_email_last_error = ?", self.database.queries[1][0])
        self.assertEqual(
            self.database.queries[1][1][0],
            "Resend did not accept the email.",
        )


if __name__ == "__main__":
    unittest.main()
