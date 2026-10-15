import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import users
from app.schemas.user import User, UserCreate, UserStatusUpdate
from app.services.auth_helpers import hash_password
from app.services.auth_service import authenticate
from app.services import user_service


class QueryResult:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount

    def fetchone(self):
        return self.row


class RegistrationDatabase:
    def __init__(self):
        self.accounts = {}
        self.user = None
        self.insert_query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params):
        if "SELECT id FROM users WHERE email" in query:
            return QueryResult()
        if "SELECT username FROM accounts" in query:
            return QueryResult(
                {"username": params[0]} if params[0] in self.accounts else None
            )
        if "INSERT INTO accounts" in query:
            username, display_name, salt, password_hash = params
            self.accounts[username] = {
                "username": username,
                "role": "inspector",
                "display_name": display_name,
                "password_salt": salt,
                "password_hash": password_hash,
            }
            return QueryResult()
        if "INSERT INTO users" in query:
            self.insert_query = query
            (
                username, name, designation, region, specialization, email, phone,
                experience_years, bio, qualifications,
            ) = params
            self.user = {
                "id": 12,
                "username": username,
                "name": name,
                "designation": designation,
                "region": region,
                "specialization": specialization,
                "email": email,
                "phone": phone,
                "experience_years": experience_years,
                "bio": bio or "",
                "qualifications": qualifications,
                "active": True,
                "status": "Pending",
                "official_id_verified": False,
                "department_unit": "Inspection Department",
                "jurisdiction": region,
            }
            return QueryResult()
        if "FROM users WHERE username" in query:
            return QueryResult(self.user if self.user["username"] == params[0] else None)
        if "SELECT a.username, a.role" in query:
            account = self.accounts.get(params[0])
            if account is None or account["role"] != params[1]:
                return QueryResult()
            return QueryResult({
                **account,
                "user_id": 12,
                "status": self.user["status"],
                "active": self.user["active"],
            })
        raise AssertionError(f"Unexpected database query: {query}")


@contextmanager
def database_context(database):
    yield database


class UserApiContractTests(unittest.TestCase):
    def setUp(self):
        self.registration_payload = {
            "name": "Priya Sharma",
            "email": "priya.sharma@example.com",
            "username": "priya.sharma",
            "password": "ChosenSecure@123",
            "confirm_password": "ChosenSecure@123",
            "phone": "9876543210",
            "designation": "Field Inspector",
            "specialization": "Financial Compliance",
            "region": "Mumbai Division",
            "experience_years": 5,
            "bio": "Brief background text.",
            "qualifications": "B.Sc. Environmental Science, ISO 14001 Lead Auditor Certificate.",
        }

    def test_registration_creates_pending_user_with_chosen_login(self):
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
            username=payload.username,
            status="Pending",
        )

        with patch("app.api.routes.users.user_service.register_user", return_value=expected) as register:
            result = users.register_user(payload)

        self.assertEqual(result, expected)
        self.assertEqual(result.status, "Pending")
        self.assertEqual(result.username, "priya.sharma")
        register.assert_called_once_with(payload)
        route = next(route for route in users.public_router.routes if route.path == "/users/register")
        self.assertEqual(route.status_code, 201)

    def test_registration_requires_matching_password_confirmation(self):
        values = {**self.registration_payload, "confirm_password": "Different@123"}
        with self.assertRaisesRegex(ValidationError, "must match"):
            UserCreate.model_validate(values)

    def test_registration_rejects_short_passwords_and_invalid_usernames(self):
        with self.assertRaises(ValidationError):
            UserCreate.model_validate({**self.registration_payload, "password": "short", "confirm_password": "short"})
        with self.assertRaises(ValidationError):
            UserCreate.model_validate({**self.registration_payload, "username": "has spaces"})

    def test_registration_maps_duplicate_username_to_conflict(self):
        payload = UserCreate.model_validate(self.registration_payload)
        with patch(
            "app.api.routes.users.user_service.register_user",
            side_effect=ValueError("username_exists"),
        ):
            with self.assertRaises(HTTPException) as raised:
                users.register_user(payload)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "Username is already assigned.")

    def test_registration_hashes_password_and_never_persists_plaintext(self):
        database = RegistrationDatabase()
        payload = UserCreate.model_validate(self.registration_payload)
        with patch.object(
            user_service, "get_connection", side_effect=lambda: database_context(database)
        ):
            result = user_service.register_user(payload)

        account = database.accounts["priya.sharma"]
        self.assertNotEqual(account["password_hash"], payload.password)
        self.assertEqual(
            hash_password(payload.password, bytes.fromhex(account["password_salt"])),
            account["password_hash"],
        )
        self.assertNotIn("temp_password", database.insert_query)
        self.assertEqual(result.status, "Pending")
        self.assertEqual(result.username, payload.username)
        self.assertNotIn("password", User.model_fields)

    def test_pending_inspector_can_log_in_and_receives_verification_message(self):
        database = RegistrationDatabase()
        payload = UserCreate.model_validate(self.registration_payload)
        with patch.object(
            user_service, "get_connection", side_effect=lambda: database_context(database)
        ):
            user_service.register_user(payload)

        with patch("app.services.auth_service.get_connection", side_effect=lambda: database_context(database)):
            session = authenticate(payload.username, payload.password, "Inspector")

        self.assertEqual(session["role"], "inspector")
        self.assertEqual(session["status"], "Pending")
        self.assertEqual(
            session["verificationMessage"],
            "Manual verification is in progress. Estimated completion: within 24 hours.",
        )

    def test_status_update_does_not_trigger_email_delivery(self):
        verified = User(
            id=12,
            name="Priya Sharma",
            designation="Field Inspector",
            region="Mumbai Division",
            username="priya.sharma",
            status="Verified",
        )
        with patch(
            "app.api.routes.users.user_service.update_user_status",
            return_value=verified,
        ) as update_status:
            result = users.update_user_status(12, UserStatusUpdate(status="Verified"))

        update_status.assert_called_once_with(12, "Verified")
        self.assertEqual(result.status, "Verified")
        self.assertNotIn("password", result.model_dump())


if __name__ == "__main__":
    unittest.main()
