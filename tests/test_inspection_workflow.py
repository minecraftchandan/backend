import os
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.api import security
from app.api.routes import inspection_requests, schedules, users
from app.schemas.inspection_request import InspectionRequestCreate
from app.schemas.schedule import ScheduleCreate
from app.schemas.user import InspectorProfileUpdate
from app.services import (
    inspection_request_service,
    notification_service,
    schedule_service,
    user_service,
)


class Result:
    def __init__(self, row=None, rows=None, rowcount=1):
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class RequestDatabase:
    def __init__(self):
        self.requests = {}
        self.rate_counts = {}
        self.organization = {"id": "org-1", "name": "Authoritative Organization"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=None):
        if "SELECT id FROM organizations" in query:
            return Result(self.organization if params[0] == self.organization["id"] else None)
        if "INSERT INTO inspection_request_rate_limits" in query:
            key = (params[0], params[1])
            self.rate_counts[key] = self.rate_counts.get(key, 0) + 1
            return Result({"request_count": self.rate_counts[key]})
        if "DELETE FROM inspection_request_rate_limits" in query:
            return Result(rowcount=0)
        if "INSERT INTO inspection_requests" in query:
            (
                request_id, department, contact, requester_name, requester_email,
                org_id, org_display, purpose, scope, urgency,
                proposed_scope, priority, created_at, new_org,
            ) = params
            self.requests[request_id] = {
                "id": request_id,
                "department": department,
                "contact": contact,
                "requester_name": requester_name,
                "requester_email": requester_email,
                "requester_verified": False,
                "organization_id": org_id,
                "organization": self.organization["name"],
                "purpose": purpose,
                "scope": scope,
                "urgency": urgency,
                "proposed_scope": proposed_scope,
                "priority": priority,
                "status": "Pending",
                "created_at": created_at,
                "reviewed_by": None,
                "reviewed_at": None,
            }
            return Result()
        if "UPDATE inspection_requests" in query:
            new_status, reviewed_by, reviewed_at, request_id = params
            record = self.requests.get(request_id)
            if not record or record["status"] != "Pending":
                return Result(rowcount=0)
            record.update(status=new_status, reviewed_by=reviewed_by, reviewed_at=reviewed_at)
            return Result()
        if "FROM inspection_requests r" in query:
            if "WHERE r.id = ?" in query:
                row = self.requests.get(params[0])
                if row is None:
                    return Result()
                return Result(dict(row, new_organization_json=None))
            return Result(rows=[dict(row, new_organization_json=None) for row in self.requests.values()])
        raise AssertionError(f"Unexpected request query: {query}")


class ScheduleDatabase:
    def __init__(
        self,
        request_status="Approved",
        request_org="org-1",
        active=True,
        official_id="DEMO-INS-0012",
        official_id_verified=False,
    ):
        self.request_status = request_status
        self.request_org = request_org
        self.active = active
        self.official_id = official_id
        self.official_id_verified = official_id_verified
        self.inserted = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=None):
        if "FROM organizations WHERE id" in query:
            row = {
                "id": "org-1",
                "name": "Authoritative Organization",
                "location": "District",
                "address": "1 Registered Road",
                "latitude": 18.5,
                "longitude": 73.8,
                "radius_m": 100,
            }
            return Result(row if params[0] == "org-1" else None)
        if "FROM users WHERE id" in query:
            row = {
                "id": 12,
                "name": "Inspector Name",
                "designation": "Senior Inspector",
                "official_id": self.official_id,
                "official_id_verified": self.official_id_verified,
                "qualifications": "Finance and accounting review",
            }
            return Result(row if params[0] == 12 and self.active else None)
        if "FROM inspection_requests" in query:
            if self.request_status is None:
                return Result()
            return Result({
                "organization_id": self.request_org,
                "status": self.request_status,
            })
        if "FROM schedules" in query and "SELECT id FROM schedules" in query:
            return Result()
        if "INSERT INTO schedules" in query:
            self.inserted = params
            return Result()
        if "INSERT INTO inspection_notification_outbox" in query:
            return Result()
        if "FROM schedules s" in query:
            return Result(rows=[{
                "id": "SCH-1",
                "organization": "Authoritative Organization",
                "location": "1 Registered Road",
                "date": (date.today() + timedelta(days=2)).isoformat(),
                "time": "10:30 AM",
                "inspector": "Inspector Name",
                "status": "Scheduled",
                "site_latitude": 18.5,
                "site_longitude": 73.8,
                "site_radius_m": 100,
                "purpose": "Routine inspection purpose",
                "scope": "Review records and facilities",
                "inspection_request_id": "IR-1",
                "organization_notified": False,
                "notification_status": "failed",
                "notification_error": "SMTP not configured",
                "inspector_id": 12,
                "inspector_designation": "Senior Inspector",
                "inspector_official_id": "SD-INS-0012",
                "inspector_official_id_verified": False,
                "inspector_qualifications": "Finance and accounting review",
            }])
        raise AssertionError(f"Unexpected schedule query: {query}")


class NotificationDatabase:
    def __init__(self, verified=True):
        self.outbox = {
            "status": "pending",
            "attempts": 0,
            "last_error": None,
            "recipient_email": None,
        }
        self.verified = verified
        self.schedule = {}
        self.row = {
            "schedule_id": "SCH-1",
            "outbox_status": "pending",
            "organization": "Registered Organization",
            "date": "2030-02-03",
            "time": "10:30 AM",
            "purpose": "Investigate reported concern",
            "scope": "Review records and inspect facilities",
            "inspector": "Inspector Name",
            "contact_email": "verified@example.gov",
            "contact_person": "Organization Contact",
            "contact_email_verified": verified,
            "designation": "Senior Inspector",
            "official_id": "SD-INS-0012",
            "qualifications": "Finance and accounting review",
        }
        self.last_recipient = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=None):
        if "FROM inspection_notification_outbox o" in query:
            if params[0] != "SCH-1":
                return Result()
            return Result(dict(self.row, outbox_status=self.outbox["status"]))
        if "SET status = 'sending'" in query:
            _, schedule_id = params
            if schedule_id != "SCH-1" or self.outbox["status"] not in {"pending", "failed"}:
                return Result(rowcount=0)
            self.outbox.update(
                status="sending",
                attempts=self.outbox["attempts"] + 1,
                recipient_email=params[0],
            )
            self.last_recipient = params[0]
            return Result()
        if "SET notification_status = 'sending'" in query:
            return Result()
        if "SELECT status FROM inspection_notification_outbox" in query:
            if params[0] != "SCH-1":
                return Result()
            return Result({"status": self.outbox["status"]})
        if "UPDATE inspection_notification_outbox" in query:
            state, error, _delivered, schedule_id = params
            self.outbox.update(status=state, last_error=error)
            return Result()
        if "UPDATE schedules" in query:
            notified, state, error, schedule_id = params
            self.schedule[schedule_id] = {
                "organization_notified": notified,
                "notification_status": state,
                "notification_error": error,
            }
            return Result()
        raise AssertionError(f"Unexpected notification query: {query}")


class UserProfileDatabase:
    def __init__(self):
        self.profile = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=None):
        if "UPDATE users" in query:
            self.profile = {
                "id": params[9],
                "name": params[0],
                "designation": params[1],
                "official_id": params[2],
                "department_unit": params[4],
                "official_id_verified": params[3],
                "jurisdiction": params[5],
                "qualifications": params[7],
                "active": params[8],
                "region": params[6],
            }
            return Result(rowcount=1)
        if "FROM users WHERE id" in query:
            return Result(
                dict(self.profile)
                if self.profile and params[0] == self.profile["id"]
                else None
            )
        raise AssertionError(f"Unexpected user query: {query}")


@contextmanager
def database_context(database):
    yield database


def valid_request(**updates):
    values = {
        "department": "Department of Welfare",
        "requester_name": "Officer Name",
        "requester_email": "officer@example.gov",
        "organization_id": "org-1",
        "organization": "Untrusted display name",
        "purpose": "Review compliance concerns",
        "scope": "Review records and inspect facilities",
        "urgency": "Routine",
    }
    values.update(updates)
    return InspectionRequestCreate.model_validate(values)


def valid_schedule(**updates):
    values = {
        "organization_id": "org-1",
        "inspector_id": 12,
        "date": date.today() + timedelta(days=2),
        "time": "10:30",
        "purpose": "Review compliance concerns",
        "scope": "Review records and inspect facilities",
        "inspection_request_id": "IR-1",
        "notify_organization": False,
    }
    values.update(updates)
    return ScheduleCreate.model_validate(values)


class InspectionRequestWorkflowTests(unittest.TestCase):
    def test_submission_persists_unverified_contact_and_authoritative_name(self):
        database = RequestDatabase()
        with patch.object(
            inspection_request_service, "get_connection", side_effect=lambda: database_context(database)
        ):
            request = inspection_request_service.submit_inspection_request(
                valid_request(), "192.0.2.10"
            )

        self.assertTrue(request.id.startswith("IR-"))
        self.assertEqual(request.status, "Pending")
        self.assertFalse(request.requester_verified)
        self.assertEqual(request.organization, "Authoritative Organization")
        self.assertNotEqual(request.organization, "Untrusted display name")
        self.assertTrue(request.created_at.endswith("+00:00"))

    def test_submission_rejects_unknown_organization(self):
        database = RequestDatabase()
        with patch.object(
            inspection_request_service, "get_connection", side_effect=lambda: database_context(database)
        ):
            with self.assertRaises(LookupError):
                inspection_request_service.submit_inspection_request(
                    valid_request(organization_id="unknown"), "192.0.2.10"
                )

    def test_submission_validates_email_urgency_and_meaningful_scope(self):
        for values in (
            {"requester_email": "not-an-email"},
            {"urgency": "Emergency"},
            {"scope": "short"},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                valid_request(**values)

    def test_submission_is_rate_limited(self):
        database = RequestDatabase()
        with patch.object(
            inspection_request_service, "get_connection", side_effect=lambda: database_context(database)
        ):
            for _ in range(inspection_request_service.RATE_LIMIT_REQUESTS):
                inspection_request_service.submit_inspection_request(
                    valid_request(), "192.0.2.10"
                )
            with self.assertRaises(inspection_request_service.RateLimitExceeded):
                inspection_request_service.submit_inspection_request(
                    valid_request(), "192.0.2.10"
                )

    def test_approval_and_rejection_are_one_time_transitions(self):
        database = RequestDatabase()
        with patch.object(
            inspection_request_service, "get_connection", side_effect=lambda: database_context(database)
        ):
            pending = inspection_request_service.submit_inspection_request(
                valid_request(), "192.0.2.11"
            )
            approved = inspection_request_service.review_inspection_request(
                pending.id, "Approved", "authority@example.gov"
            )
            self.assertEqual(approved.status, "Approved")
            self.assertEqual(approved.reviewed_by, "authority@example.gov")
            self.assertIsNotNone(approved.reviewed_at)
            with self.assertRaises(inspection_request_service.InvalidRequestTransition):
                inspection_request_service.review_inspection_request(
                    pending.id, "Rejected", "authority@example.gov"
                )

    def test_pending_request_can_be_rejected(self):
        database = RequestDatabase()
        with patch.object(
            inspection_request_service, "get_connection", side_effect=lambda: database_context(database)
        ):
            pending = inspection_request_service.submit_inspection_request(
                valid_request(), "192.0.2.12"
            )
            rejected = inspection_request_service.review_inspection_request(
                pending.id, "Rejected", "authority@example.gov"
            )
        self.assertEqual(rejected.status, "Rejected")
        self.assertEqual(rejected.reviewed_by, "authority@example.gov")
        self.assertIsNotNone(rejected.reviewed_at)


class AuthorizationTests(unittest.TestCase):
    def test_inbox_and_schedule_mutations_require_authority_dependency(self):
        route_checks = (
            (inspection_requests.authority_router, "GET", "/inspection-requests"),
            (inspection_requests.authority_router, "PATCH", "/inspection-requests/{request_id}"),
            (schedules.router, "POST", "/schedule"),
            (schedules.router, "POST", "/schedule/{schedule_id}/notification/retry"),
            (users.router, "PUT", "/users/{user_id}/profile"),
        )
        for router, method, path in route_checks:
            route = next(item for item in router.routes if item.path == path and method in item.methods)
            self.assertTrue(
                any(dependency.call is security.require_authority_officer
                    for dependency in route.dependant.dependencies),
                f"{method} {path} lacks Authority Officer authorization",
            )
        public_post = next(
            item for item in inspection_requests.public_router.routes
            if item.path == "/inspection-requests" and "POST" in item.methods
        )
        self.assertFalse(public_post.dependant.dependencies)

    def test_inspector_and_missing_user_session_are_denied(self):
        with self.assertRaises(HTTPException) as inspector:
            security.require_authority_officer({"role": "inspector", "sub": "inspector"})
        self.assertEqual(inspector.exception.status_code, 403)
        with self.assertRaises(HTTPException) as missing:
            security.require_authenticated_user(None)
        self.assertEqual(missing.exception.status_code, 401)

    def test_shared_api_secret_does_not_authenticate_as_an_officer(self):
        with patch.dict(os.environ, {"API_ACCESS_TOKEN": "s" * 40}):
            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials="s" * 40,
            )
            with self.assertRaises(HTTPException) as raised:
                security.require_authenticated_user(credentials)
        self.assertEqual(raised.exception.status_code, 401)


class ScheduleWorkflowTests(unittest.TestCase):
    def test_approved_request_can_be_linked_and_purpose_scope_are_returned(self):
        database = ScheduleDatabase()
        with patch.object(
            schedule_service, "get_connection", side_effect=lambda: database_context(database)
        ), patch.object(
            schedule_service.notification_service,
            "deliver_schedule_notification",
            return_value={
                "organization_notified": True,
                "notification_status": "sent",
                "notification_error": None,
            },
        ):
            schedule = schedule_service.create_scheduled_inspection(
                valid_schedule(notify_organization=True)
            )

        self.assertEqual(schedule.organization, "Authoritative Organization")
        self.assertEqual(schedule.purpose, "Review compliance concerns")
        self.assertEqual(schedule.scope, "Review records and inspect facilities")
        self.assertEqual(schedule.inspector_designation, "Senior Inspector")
        self.assertEqual(schedule.inspector_official_id, "DEMO-INS-0012")
        self.assertFalse(schedule.inspector_official_id_verified)
        self.assertEqual(
            schedule.inspector_qualifications,
            "Finance and accounting review",
        )
        self.assertTrue(schedule.organization_notified)
        self.assertEqual(schedule.notification_status, "sent")

    def test_pending_rejected_cross_organization_and_missing_requests_are_rejected(self):
        cases = (
            (ScheduleDatabase(request_status="Pending"), ValueError),
            (ScheduleDatabase(request_status="Rejected"), ValueError),
            (ScheduleDatabase(request_org="other-org"), ValueError),
            (ScheduleDatabase(request_status=None), LookupError),
        )
        for database, error_type in cases:
            with self.subTest(database=database), patch.object(
                schedule_service, "get_connection", side_effect=lambda: database_context(database)
            ), self.assertRaises(error_type):
                schedule_service.create_scheduled_inspection(valid_schedule())

    def test_inactive_inspector_is_not_assignable(self):
        database = ScheduleDatabase(active=False)
        with patch.object(
            schedule_service, "get_connection", side_effect=lambda: database_context(database)
        ), self.assertRaises(LookupError):
            schedule_service.create_scheduled_inspection(valid_schedule())

    def test_inspector_without_verified_official_id_cannot_be_scheduled(self):
        database = ScheduleDatabase(official_id=None)
        with patch.object(
            schedule_service, "get_connection", side_effect=lambda: database_context(database)
        ), self.assertRaises(ValueError):
            schedule_service.create_scheduled_inspection(valid_schedule())

    def test_production_rejects_demo_inspector_ids(self):
        database = ScheduleDatabase()
        with patch.object(
            schedule_service, "get_connection", side_effect=lambda: database_context(database)
        ), patch.dict(os.environ, {"APP_ENV": "production"}), self.assertRaises(ValueError):
            schedule_service.create_scheduled_inspection(valid_schedule())

    def test_production_requires_officer_verified_real_id(self):
        database = ScheduleDatabase(
            official_id="FIN-INS-2041",
            official_id_verified=False,
        )
        with patch.object(
            schedule_service,
            "get_connection",
            side_effect=lambda: database_context(database),
        ), patch.dict(os.environ, {"APP_ENV": "production"}), self.assertRaises(ValueError):
            schedule_service.create_scheduled_inspection(valid_schedule())

    def test_production_accepts_officer_verified_real_id(self):
        database = ScheduleDatabase(
            official_id="FIN-INS-2041",
            official_id_verified=True,
        )
        with patch.object(
            schedule_service,
            "get_connection",
            side_effect=lambda: database_context(database),
        ), patch.object(
            schedule_service.notification_service,
            "deliver_schedule_notification",
            return_value={
                "organization_notified": False,
                "notification_status": "failed",
                "notification_error": "No verified organization contact email is on file.",
            },
        ), patch.dict(os.environ, {"APP_ENV": "production"}):
            schedule = schedule_service.create_scheduled_inspection(
                valid_schedule(notify_organization=True)
            )
        self.assertEqual(schedule.inspector_official_id, "FIN-INS-2041")
        self.assertTrue(schedule.inspector_official_id_verified)

    def test_staging_accepts_manual_test_profile_without_verifying_its_id(self):
        database = ScheduleDatabase(
            official_id="STAGING-MANUAL-TEST-ID",
            official_id_verified=False,
        )
        with patch.object(
            schedule_service,
            "get_connection",
            side_effect=lambda: database_context(database),
        ), patch.object(
            schedule_service.notification_service,
            "deliver_schedule_notification",
            return_value={
                "organization_notified": False,
                "notification_status": "suppressed",
                "notification_error": "Staging notification was suppressed.",
            },
        ), patch.dict(os.environ, {"APP_ENV": "staging"}):
            schedule = schedule_service.create_scheduled_inspection(
                valid_schedule(notify_organization=True)
            )
        self.assertEqual(schedule.inspector_official_id, "STAGING-MANUAL-TEST-ID")
        self.assertFalse(schedule.inspector_official_id_verified)
        self.assertFalse(schedule.organization_notified)

    def test_purpose_and_scope_are_required(self):
        with self.assertRaises(ValidationError):
            valid_schedule(purpose="")
        with self.assertRaises(ValidationError):
            valid_schedule(scope="too short")
        with self.assertRaises(ValidationError):
            valid_schedule(time="10:30:00")

    def test_schedule_cannot_be_created_in_the_past(self):
        database = ScheduleDatabase()
        with patch.object(
            schedule_service, "get_connection", side_effect=lambda: database_context(database)
        ), self.assertRaises(ValueError):
            schedule_service.create_scheduled_inspection(
                valid_schedule(date=date.today() - timedelta(days=1))
            )

    def test_schedule_read_includes_purpose_and_scope_for_inspectors(self):
        database = ScheduleDatabase()
        with patch.object(
            schedule_service, "get_connection", side_effect=lambda: database_context(database)
        ), patch.dict(os.environ, {"SITE_LOCATIONS_JSON": "{}"}):
            schedules = schedule_service.get_all_schedules()
        self.assertEqual(schedules[0].purpose, "Routine inspection purpose")
        self.assertEqual(schedules[0].scope, "Review records and facilities")

    def test_historical_schedule_without_new_fields_remains_valid(self):
        from app.schemas.schedule import ScheduleItem

        item = ScheduleItem(
            id="SCH-OLD",
            organization="Legacy Organization",
            location="District",
            date="2025-01-01",
            time="10:30 AM",
            inspector="Legacy Inspector",
            status="Completed",
        )
        self.assertIsNone(item.purpose)
        self.assertIsNone(item.scope)
        self.assertFalse(item.organization_notified)


class NotificationWorkflowTests(unittest.TestCase):
    def test_missing_verified_contact_is_persisted_as_failure(self):
        database = NotificationDatabase(verified=False)
        with patch.object(
            notification_service, "get_connection", side_effect=lambda: database_context(database)
        ), patch.object(notification_service, "_send_schedule_email") as send:
            result = notification_service.deliver_schedule_notification("SCH-1")
        send.assert_not_called()
        self.assertFalse(result["organization_notified"])
        self.assertEqual(result["notification_status"], "failed")
        self.assertEqual(database.outbox["attempts"], 1)
        self.assertIn("No verified organization contact", database.outbox["last_error"])

    def test_provider_failure_is_persisted_and_retry_can_succeed(self):
        database = NotificationDatabase()
        with patch.object(
            notification_service, "get_connection", side_effect=lambda: database_context(database)
        ), patch.object(
            notification_service,
            "_send_schedule_email",
            side_effect=[
                (False, "The email provider could not accept the notification."),
                (True, None),
            ],
        ):
            failed = notification_service.deliver_schedule_notification("SCH-1")
            self.assertFalse(failed["organization_notified"])
            self.assertEqual(database.outbox["status"], "failed")
            self.assertIsNotNone(database.outbox["last_error"])
            sent = notification_service.retry_schedule_notification("SCH-1")

        self.assertTrue(sent["organization_notified"])
        self.assertEqual(database.outbox["status"], "sent")
        self.assertEqual(database.outbox["attempts"], 2)
        self.assertTrue(database.schedule["SCH-1"]["organization_notified"])
        with patch.object(
            notification_service, "get_connection", side_effect=lambda: database_context(database)
        ), self.assertRaises(ValueError):
            notification_service.retry_schedule_notification("SCH-1")

    def test_smtp_message_contains_inspection_and_inspector_details(self):
        row = {
            "organization": "Registered Organization",
            "date": "2030-02-03",
            "time": "10:30 AM",
            "purpose": "Investigate reported concern",
            "scope": "Review records and inspect facilities",
            "inspector": "Inspector Name",
            "contact_email": "verified@example.gov",
            "designation": "Senior Inspector",
            "official_id": "SD-INS-0012",
            "qualifications": "Finance and accounting review",
        }
        smtp = unittest.mock.MagicMock()
        smtp.__enter__.return_value = smtp
        smtp.send_message.return_value = {}
        with patch.dict(os.environ, {
            "SMTP_HOST": "smtp.example.gov",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "",
            "SMTP_PASSWORD": "",
            "SMTP_FROM_EMAIL": "notices@example.gov",
            "SMTP_USE_TLS": "true",
        }), patch.object(notification_service.smtplib, "SMTP", return_value=smtp):
            sent, error = notification_service._send_schedule_email(row)

        self.assertTrue(sent)
        self.assertIsNone(error)
        message = smtp.send_message.call_args.args[0]
        body = message.get_content()
        for expected in (
            "2030-02-03",
            "10:30 AM",
            row["purpose"],
            row["scope"],
            row["inspector"],
            row["designation"],
            row["official_id"],
            row["qualifications"],
        ):
            self.assertIn(expected, body)

    def test_unconfigured_provider_does_not_report_delivery(self):
        with patch.dict(os.environ, {
            "SMTP_HOST": "",
            "SMTP_FROM_EMAIL": "",
            "SMTP_USERNAME": "",
            "SMTP_PASSWORD": "",
        }):
            delivered, error = notification_service._send_schedule_email({})
        self.assertFalse(delivered)
        self.assertIn("not configured", error)

    def test_staging_notification_routes_only_to_configured_test_inbox(self):
        database = NotificationDatabase(verified=True)
        with patch.object(
            notification_service,
            "get_connection",
            side_effect=lambda: database_context(database),
        ), patch.object(
            notification_service,
            "_send_schedule_email",
            return_value=(True, None),
        ) as send, patch.dict(os.environ, {
            "APP_ENV": "staging",
            "STAGING_NOTIFICATION_TEST_INBOX": "staging-inbox@example.test",
        }):
            result = notification_service.deliver_schedule_notification("SCH-1")

        self.assertEqual(send.call_args.kwargs["recipient"], "staging-inbox@example.test")
        self.assertEqual(database.last_recipient, "staging-inbox@example.test")
        self.assertFalse(result["organization_notified"])
        self.assertEqual(result["notification_status"], "test_sent")
        self.assertIn("organization was not notified", result["notification_error"])
        self.assertFalse(database.schedule["SCH-1"]["organization_notified"])
        self.assertEqual(database.outbox["status"], "test_sent")

    def test_staging_without_test_inbox_suppresses_delivery(self):
        database = NotificationDatabase(verified=True)
        with patch.object(
            notification_service,
            "get_connection",
            side_effect=lambda: database_context(database),
        ), patch.object(notification_service, "_send_schedule_email") as send, patch.dict(
            os.environ,
            {"APP_ENV": "staging", "STAGING_NOTIFICATION_TEST_INBOX": ""},
        ):
            result = notification_service.deliver_schedule_notification("SCH-1")

        send.assert_not_called()
        self.assertIsNone(database.last_recipient)
        self.assertFalse(result["organization_notified"])
        self.assertEqual(result["notification_status"], "suppressed")
        self.assertEqual(database.outbox["status"], "suppressed")
        self.assertFalse(database.schedule["SCH-1"]["organization_notified"])


class InspectorProfileTests(unittest.TestCase):
    def test_authority_officer_can_save_backend_managed_profile(self):
        profile = InspectorProfileUpdate(
            name=" Inspector Name ",
            designation="Senior Inspector",
            official_id="OFF-1234",
            official_id_verified=True,
            department_unit="Inspection Unit",
            jurisdiction="Northern District",
            qualifications="Finance audit",
            active=True,
        )
        database = UserProfileDatabase()
        with patch.object(
            user_service, "get_connection", side_effect=lambda: database_context(database)
        ):
            saved = user_service.update_inspector_profile(12, profile)
        self.assertEqual(saved.official_id, "OFF-1234")
        self.assertTrue(saved.official_id_verified)
        self.assertEqual(saved.jurisdiction, "Northern District")
        self.assertEqual(saved.qualifications, "Finance audit")
        self.assertTrue(saved.active)
        self.assertEqual(saved.name, "Inspector Name")

    def test_official_id_must_be_provided(self):
        with self.assertRaises(ValidationError):
            InspectorProfileUpdate(
                name="Inspector Name",
                designation="Inspector",
                official_id=" ",
                department_unit="Inspection Unit",
                jurisdiction="Northern District",
                active=True,
            )


if __name__ == "__main__":
    unittest.main()
