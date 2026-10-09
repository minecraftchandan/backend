"""SMTP delivery and retry handling for organization schedule notices."""

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

from app.database import get_connection


def deliver_schedule_notification(schedule_id: str) -> dict:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT o.schedule_id, o.status AS outbox_status, s.organization,
                s.date, s.time, s.purpose, s.scope, s.inspector,
                org.contact_email, org.contact_person,
                org.contact_email_verified, u.designation, u.official_id
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
            return {
                "organization_notified": True,
                "notification_status": "sent",
                "notification_error": None,
            }

        claim = connection.execute(
            """UPDATE inspection_notification_outbox
            SET status = 'sending', attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP,
                recipient_email = ?, last_error = NULL
            WHERE schedule_id = ?
                AND (status IN ('pending', 'failed')
                    OR (status = 'sending'
                        AND updated_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'))""",
            (
                row["contact_email"] if row["contact_email_verified"] else None,
                schedule_id,
            ),
        )
        if claim.rowcount == 0:
            return {
                "organization_notified": False,
                "notification_status": row["outbox_status"],
                "notification_error": "Notification delivery is already in progress.",
            }
        connection.execute(
            """UPDATE schedules
            SET notification_status = 'sending', notification_error = NULL
            WHERE id = ?""",
            (schedule_id,),
        )

    if not row["contact_email_verified"] or not row["contact_email"]:
        error = "No verified organization contact email is on file."
        delivered = False
    else:
        delivered, error = _send_schedule_email(row)

    state = "sent" if delivered else "failed"
    with get_connection() as connection:
        connection.execute(
            """UPDATE inspection_notification_outbox
            SET status = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP,
                delivered_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE delivered_at END
            WHERE schedule_id = ?""",
            (state, error, delivered, schedule_id),
        )
        connection.execute(
            """UPDATE schedules
            SET organization_notified = ?, notification_status = ?, notification_error = ?
            WHERE id = ?""",
            (delivered, state, error, schedule_id),
        )
    return {
        "organization_notified": delivered,
        "notification_status": state,
        "notification_error": error,
    }


def retry_schedule_notification(schedule_id: str) -> dict:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT status FROM inspection_notification_outbox
            WHERE schedule_id = ?""",
            (schedule_id,),
        ).fetchone()
    if row is None:
        raise LookupError("No retryable organization notification exists for this schedule.")
    if row["status"] == "sent":
        raise ValueError("The organization notification has already been accepted by the provider.")
    return deliver_schedule_notification(schedule_id)


def _send_schedule_email(row) -> tuple[bool, Optional[str]]:
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("SMTP_FROM_EMAIL", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if not host or not sender:
        return False, "SMTP email delivery is not configured."
    if bool(username) != bool(password):
        return False, "SMTP_USERNAME and SMTP_PASSWORD must both be configured."

    try:
        port = int(os.getenv("SMTP_PORT", "587"))
        use_tls_value = os.getenv("SMTP_USE_TLS", "true").strip().lower()
        if use_tls_value not in {"true", "false"}:
            return False, "SMTP_USE_TLS must be true or false."
        message = EmailMessage()
        message["Subject"] = f"Inspection scheduled for {row['organization']}"
        message["From"] = sender
        message["To"] = row["contact_email"]
        message.set_content(
            "\n".join((
                f"An inspection has been scheduled for {row['organization']}.",
                f"Date: {row['date']}",
                f"Time: {row['time']}",
                f"Purpose: {row['purpose']}",
                f"Scope: {row['scope']}",
                f"Assigned inspector: {row['inspector']}",
                f"Designation: {row['designation'] or 'Not recorded'}",
                f"Official ID: {row['official_id'] or 'Not recorded'}",
            ))
        )
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            if use_tls_value == "true":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if username:
                server.login(username, password)
            refused = server.send_message(message)
        if refused:
            return False, "The email provider rejected the recipient."
    except (OSError, smtplib.SMTPException, ValueError):
        return False, "The email provider could not accept the notification."
    return True, None
