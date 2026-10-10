"""SMTP delivery for inspection schedule notices."""

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional


def send_schedule_email(row, recipient: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """
    Compose and send a schedule notice. Returns (provider_accepted, error_message).
    Defaults recipient to row["contact_email"] if not provided.
    """
    if recipient is None:
        recipient = row.get("contact_email", "")
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
        use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower()
        if use_tls not in {"true", "false"}:
            return False, "SMTP_USE_TLS must be true or false."

        message = EmailMessage()
        message["Subject"] = f"Inspection scheduled for {row['organization']}"
        message["From"] = sender
        message["To"] = recipient
        message.set_content("\n".join((
            f"An inspection has been scheduled for {row['organization']}.",
            f"Date: {row['date']}",
            f"Time: {row['time']}",
            f"Purpose: {row['purpose']}",
            f"Scope: {row['scope']}",
            f"Assigned inspector: {row['inspector']}",
            f"Designation: {row['designation'] or 'Not recorded'}",
            f"Official ID: {row['official_id'] or 'Not recorded'}",
            f"Qualifications: {row['qualifications'] or 'Not recorded'}",
        )))

        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            if use_tls == "true":
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
