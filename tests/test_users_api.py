import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.routes import users
from app.schemas.user import User, UserCreate, UserFullUpdate, UserStatusUpdate
from app.services.auth_helpers import hash_password
from app.services.email.resend import EmailDeliveryError
from app.services.user_service import _replace_account_credentials


class AccountDatabase:
    def __init__(self, accounts=None):
        self.accounts = accounts or {}
        self.inserted = None

    def execute(self, query, params):
        if "SELECT username FROM accounts" in query:
            username = params[0]
            return QueryResult({"username": username} if username in self.accounts else None)
        if "INSERT INTO accounts" in query:
            self.inserted = params
            self.accounts[params[0]] = {
                "role": params[1],
                "display_name": params[2],
                "password_salt": params[3],
                "password_hash": params[4],
            }
            return QueryResult()
        raise AssertionError(f"Unexpected account query: {query}")


class QueryResult:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class UserApiContractTests(unittest.TestCase):
    def setUp(self):
        self.registration_payload = {
            "name": "Priya Sharma",
            "email": "priya.sharma@example.com",
            "phone": "9876543210",
            "designation": "Field Inspector",
            "specialization": "Financial Compliance",
            "region": "Mumbai Division",
            "experience_years": 5,
            "bio": "Brief background text.",
            "qualifications": "B.Sc. Environmental Science, ISO 14001 Lead Auditor Certificate.",
        }

    def test_registration_accepts_passwordless_payload_and_returns_pending_user(self):
        payload = UserCreate.model_validate(self.registration_payload)
        expected = User(
            id=12,
            name=payload.name,
            designation=payload.designation,
            region=payload.region,
            specialization=payload.specialization,
            email=payload.email,
            phone=payload.phone,
            experience_years=payload.experience_years,
            bio=payload.bio,
            qualifications=payload.qualifications,
            username=None,
            status=None,
        )

        with patch("app.api.routes.users.user_service.register_user", return_value=expected) as register:
            result = users.register_user(payload)

        self.assertEqual(result, expected)
        self.assertIsNone(result.status)
        self.assertIsNone(result.username)
        register.assert_called_once_with(payload)
        route = next(route for route in users.public_router.routes if route.path == "/users/register")
        self.assertEqual(route.status_code, 201)

    def test_registration_normalizes_blank_optional_bio(self):
        payload = UserCreate.model_validate({**self.registration_payload, "bio": None})

        self.assertEqual(payload.bio, "")

    def test_registration_returns_documented_conflict_for_duplicate_email(self):
        payload = UserCreate.model_validate(self.registration_payload)
        with patch(
            "app.api.routes.users.user_service.register_user",
            side_effect=ValueError("email_exists"),
        ):
            with self.assertRaises(HTTPException) as raised:
                users.register_user(payload)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "Email already registered.")

    def test_authority_update_accepts_credentials_and_qualifications(self):
        payload = UserFullUpdate.model_validate({
            **self.registration_payload,
            "username": "priya.sharma",
            "password": "Approved@123",
        })

        self.assertEqual(payload.username, "priya.sharma")
        self.assertEqual(payload.password, "Approved@123")
        self.assertEqual(payload.qualifications, self.registration_payload["qualifications"])

    def test_credential_assignment_hashes_password(self):
        database = AccountDatabase()

        old_username = _replace_account_credentials(
            database, None, "priya.sharma", "Priya Sharma", "Approved@123"
        )

        account = database.accounts["priya.sharma"]
        self.assertIsNone(old_username)
        self.assertNotEqual(account["password_hash"], "Approved@123")
        self.assertEqual(
            hash_password("Approved@123", bytes.fromhex(account["password_salt"])),
            account["password_hash"],
        )

    def test_credential_assignment_rejects_existing_username(self):
        existing = {
            "role": "inspector",
            "display_name": "Existing Inspector",
            "password_salt": "existing-salt",
            "password_hash": "existing-hash",
        }
        database = AccountDatabase({"taken.username": existing})

        with self.assertRaisesRegex(ValueError, "username_exists"):
            _replace_account_credentials(
                database, None, "taken.username", "Priya Sharma", "Approved@123"
            )

        self.assertIsNone(database.inserted)
        self.assertEqual(database.accounts["taken.username"], existing)

    def test_verification_sends_assigned_credentials_without_returning_password(self):
        inspector = User(
            id=12,
            name="Priya Sharma",
            email="priya.sharma@example.com",
            username="priya.sharma",
            password="Temporary@123",
            designation="Field Inspector",
            region="Mumbai Division",
        )
        verified = inspector.model_copy(update={"status": "Verified"})
        with patch(
            "app.api.routes.users.user_service.get_user_by_id",
            side_effect=[inspector, verified],
        ) as get_user, patch(
            "app.api.routes.users.user_service.update_user_status",
            return_value=verified,
        ), patch(
            "app.api.routes.users.deliver_inspector_credentials_email",
            return_value=True,
        ) as send_email:
            result = users.update_user_status(12, UserStatusUpdate(status="Verified"))

        get_user.assert_any_call(12)
        send_email.assert_called_once_with(12)
        self.assertIsNone(result.password)
        self.assertEqual(result.status, "Verified")

    def test_verification_delivery_failure_leaves_inspector_verified(self):
        inspector = User(
            id=12,
            name="Priya Sharma",
            email="priya.sharma@example.com",
            designation="Field Inspector",
            region="Mumbai Division",
        )
        with patch(
            "app.api.routes.users.user_service.get_user_by_id",
            return_value=inspector,
        ), patch(
            "app.api.routes.users.user_service.update_user_status"
        ) as update_status, patch(
            "app.api.routes.users.deliver_inspector_credentials_email",
            side_effect=EmailDeliveryError(
                "Assign an email, username, and password before sending credentials.",
                status_code=409,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                users.update_user_status(12, UserStatusUpdate(status="Verified"))

        self.assertEqual(raised.exception.status_code, 409)
        update_status.assert_called_once_with(12, "Verified")

    def test_resend_failure_reports_that_inspector_was_already_verified(self):
        inspector = User(
            id=12,
            name="Priya Sharma",
            email="priya.sharma@example.com",
            username="priya.sharma",
            password="Temporary@123",
            designation="Field Inspector",
            region="Mumbai Division",
        )
        with patch(
            "app.api.routes.users.user_service.get_user_by_id",
            return_value=inspector,
        ), patch(
            "app.api.routes.users.user_service.update_user_status",
            return_value=inspector.model_copy(update={"status": "Verified"}),
        ), patch(
            "app.api.routes.users.deliver_inspector_credentials_email",
            side_effect=EmailDeliveryError("Resend did not accept the email."),
        ):
            with self.assertRaises(HTTPException) as raised:
                users.update_user_status(12, UserStatusUpdate(status="Verified"))

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("marked Verified", raised.exception.detail)

    def test_manual_email_endpoint_calls_delivery_and_returns_sent_state(self):
        inspector = User(
            id=12,
            name="Priya Sharma",
            email="priya.sharma@example.com",
            username="priya.sharma",
            designation="Field Inspector",
            region="Mumbai Division",
            status="Verified",
            email_sent=True,
        )
        with patch(
            "app.api.routes.users.deliver_inspector_credentials_email",
            return_value=True,
        ) as send_email, patch(
            "app.api.routes.users.user_service.get_user_by_id",
            return_value=inspector,
        ):
            result = users.resend_inspector_credentials_email(12)

        send_email.assert_called_once_with(12)
        self.assertTrue(result.email_sent)


if __name__ == "__main__":
    unittest.main()