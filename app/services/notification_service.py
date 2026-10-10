"""Outbox state machine for organization schedule notices."""

import os
import smtplib

from app.database import get_connection
from app.services.smtp import send_schedule_email as _send_schedule_email


def deliver_schedule_notification(schedule_id: str) -> dict:
    staging = os.getenv("APP_ENV", "development").strip().lower() == "staging"
    staging_recipient = os.getenv("STAGING_NOTIFICATION_TEST_INBOX", "").strip()

    with get_connection() as connection:
        row = connection.execute(
            """SELECT o.schedule_id, o.status AS outbox_status, s.organization,
                s.date, s.time, s.purpose, s.scope, s.inspector,
                org.contact_email, org.contact_person,
                org.contact_email_verified, u.designation, u.official_id,
                u.qualifications
            FROM inspection_notification_outbox o
            JOIN schedules s ON s.id = o.schedule_id
            JOIN organizations org ON org.name = s.organization
            LEFT JOIN users u ON u.id = s.inspector_id
            WHERE o.schedule_id = ?""",
            (schedule_id,),
        ).fetchone()
        if row is None:
            raise LookupError("No organization notification is queued for this schedule.")
        if row["outbox_status"] == "sent":
            return {"organization_notified": True, "notification_status": "sent", "notification_error": None}
        if row["outbox_status"] in {"test_sent", "suppressed"}:
            return {
                "organization_notified": False,
                "notification_status": row["outbox_status"],
                "notification_error": (
                    "Staging notice was accepted by the test inbox; the organization was not notified."
                    if row["outbox_status"] == "test_sent"
                    else "Staging notification was suppressed; the organization was not notified."
                ),
            }

        recipient = staging_recipient or None if staging else (
            row["contact_email"] if row["contact_email_verified"] else None
        )
        claim = connection.execute(
            """UPDATE inspection_notification_outbox
            SET status = 'sending', attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP,
                recipient_email = ?, last_error = NULL
            WHERE schedule_id = ?
                AND (status IN ('pending', 'failed')
                    OR (status = 'sending'
                        AND updated_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'))""",
            (recipient, schedule_id),
        )
        if claim.rowcount == 0:
            return {
                "organization_notified": False,
                "notification_status": row["outbox_status"],
                "notification_error": "Notification delivery is already in progress.",
            }
        connection.execute(
            "UPDATE schedules SET notification_status = 'sending', notification_error = NULL WHERE id = ?",
            (schedule_id,),
        )

    if staging and not staging_recipient:
        error = "Staging notification was suppressed; the organization was not notified."
        delivered, provider_accepted, state = False, False, "suppressed"
    elif not staging and (not row["contact_email_verified"] or not row["contact_email"]):
        error = "No verified organization contact email is on file."
        delivered, provider_accepted, state = False, False, "failed"
    else:
        recipient = staging_recipient if staging else row["contact_email"]
        provider_accepted, error = _send_schedule_email(row, recipient=recipient)
        delivered = provider_accepted and not staging
        state = "test_sent" if (staging and provider_accepted) else ("sent" if delivered else "failed")
        if staging and provider_accepted:
            error = "Staging notice accepted by the test inbox; the organization was not notified."

    with get_connection() as connection:
        connection.execute(
            """UPDATE inspection_notification_outbox
            SET status = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP,
                delivered_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE delivered_at END
            WHERE schedule_id = ?""",
            (state, error, provider_accepted, schedule_id),
        )
        connection.execute(
            "UPDATE schedules SET organization_notified = ?, notification_status = ?, notification_error = ? WHERE id = ?",
            (delivered, state, error, schedule_id),
        )
    return {"organization_notified": delivered, "notification_status": state, "notification_error": error}


def retry_schedule_notification(schedule_id: str) -> dict:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT status FROM inspection_notification_outbox WHERE schedule_id = ?",
            (schedule_id,),
        ).fetchone()
    if row is None:
        raise LookupError("No retryable organization notification exists for this schedule.")
    if row["status"] == "sent":
        raise ValueError("The organization notification has already been accepted by the provider.")
    if row["status"] == "test_sent":
        raise ValueError("The staging notice was sent to the test inbox; the organization was not notified.")
    if row["status"] == "suppressed":
        raise ValueError("The staging notification was intentionally suppressed.")
    return deliver_schedule_notification(schedule_id)
