"""Transactional inspector-account emails sent through Resend."""

import html
import json
import logging
import os
from email.utils import formataddr
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def _provider_error_message(error: HTTPError) -> str:
    try:
        body = json.loads(error.read(4096).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        body = None

    provider_name = None
    provider_message = None
    if isinstance(body, dict):
        provider_name = body.get("name") or body.get("code")
        provider_message = body.get("message") or body.get("error")
        if isinstance(provider_message, dict):
            provider_message = provider_message.get("message") or provider_message.get("detail")
        if not isinstance(provider_message, str):
            provider_message = None

    request_id = None
    if error.headers:
        request_id = (
            error.headers.get("resend-id")
            or error.headers.get("x-resend-id")
            or error.headers.get("x-request-id")
        )

    safe_provider_name = (
        provider_name.strip().replace("\r", " ").replace("\n", " ")[:100]
        if isinstance(provider_name, str) and provider_name.strip()
        else "unspecified"
    )
    safe_request_id = (
        request_id.replace("\r", " ").replace("\n", " ")[:100]
        if request_id
        else "unavailable"
    )
    safe_provider_message = (
        provider_message.strip().replace("\r", " ").replace("\n", " ")[:300]
        if provider_message and provider_message.strip()
        else None
    )
    logger.warning(
        "Resend rejected a credentials email: http_status=%s error_type=%s "
        "request_id=%s provider_message=%s",
        error.code,
        safe_provider_name,
        safe_request_id,
        safe_provider_message or "unavailable",
    )

    detail = f"Resend rejected the email (HTTP {error.code})"
    if safe_provider_message:
        detail += f": {safe_provider_message}"
    elif error.reason:
        detail += f": {str(error.reason)[:100]}"
    if request_id:
        detail += f" (request ID: {safe_request_id})"
    else:
        detail += ". Check the Render service logs for the provider error details."
    return detail


class EmailDeliveryError(RuntimeError):
    """An email could not be accepted by the configured provider."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def send_inspector_credentials_email(
    recipient: str,
    name: str,
    username: str,
    password: str,
) -> None:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = os.getenv("RESEND_FROM_EMAIL", "").strip()
    from_name = os.getenv("RESEND_FROM_NAME", "Satark Drishti").strip()
    if not api_key or not from_email:
        raise EmailDeliveryError(
            "Resend is not configured. Set RESEND_API_KEY and RESEND_FROM_EMAIL.",
            status_code=503,
        )
    if any("\r" in value or "\n" in value for value in (from_email, from_name)):
        raise EmailDeliveryError(
            "RESEND_FROM_EMAIL and RESEND_FROM_NAME must not contain line breaks.",
            status_code=503,
        )

    safe_name = html.escape(name)
    safe_username = html.escape(username)
    safe_password = html.escape(password)
    text = "\n".join((
        f"Hello {name},",
        "",
        "Your Satark Drishti inspector account has been verified and is ready.",
        f"Username: {username}",
        f"Temporary password: {password}",
        "",
        "For your security, change your password after your first sign-in.",
        "If you did not expect this message, contact your administrator.",
        "",
        "Regards,",
        "Satark Drishti Administration",
    ))
    html_content = f"""\
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
  <body style="margin:0;background:#f3f5f8;font-family:Arial,Helvetica,sans-serif;color:#172033;">
    <div style="max-width:600px;margin:32px auto;padding:0 16px;">
      <div style="background:#123b5d;padding:24px 32px;border-radius:12px 12px 0 0;">
        <div style="font-size:13px;letter-spacing:1.5px;color:#c7e5f6;text-transform:uppercase;">Satark Drishti</div>
        <h1 style="font-size:22px;line-height:1.35;color:#fff;margin:10px 0 0;">Your inspector account is ready</h1>
      </div>
      <div style="background:#fff;padding:32px;border-radius:0 0 12px 12px;box-shadow:0 8px 28px rgba(23,32,51,.08);">
        <p style="font-size:16px;line-height:1.6;margin:0 0 18px;">Hello {safe_name},</p>
        <p style="font-size:15px;line-height:1.6;margin:0 0 22px;">
          Your inspector account has been verified. Use the credentials below to sign in.
        </p>
        <div style="background:#f3f7fa;border:1px solid #dce7ef;border-radius:8px;padding:18px 20px;">
          <p style="margin:0 0 12px;font-size:14px;"><strong>Username</strong><br>{safe_username}</p>
          <p style="margin:0;font-size:14px;"><strong>Temporary password</strong><br>{safe_password}</p>
        </div>
        <p style="font-size:13px;line-height:1.6;color:#465467;margin:20px 0 0;">
          For your security, change your password after your first sign-in. If you did not
          expect this message, contact your administrator.
        </p>
        <p style="font-size:14px;line-height:1.6;margin:24px 0 0;">Regards,<br><strong>Satark Drishti Administration</strong></p>
      </div>
      <p style="font-size:11px;line-height:1.5;color:#687588;text-align:center;margin:16px 0 0;">
        This message contains account credentials. Please do not forward it.
      </p>
    </div>
  </body>
</html>"""
    payload = json.dumps({
        "from": formataddr((from_name, from_email)),
        "to": [recipient],
        "subject": "Your Satark Drishti inspector account is ready",
        "text": text,
        "html": html_content,
    }).encode("utf-8")
    request = Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            if response.status < 200 or response.status >= 300:
                raise EmailDeliveryError("Resend did not accept the email.")
    except HTTPError as error:
        raise EmailDeliveryError(_provider_error_message(error)) from error
    except (OSError, URLError, TimeoutError) as error:
        raise EmailDeliveryError("Could not connect to Resend to send the email.") from error
