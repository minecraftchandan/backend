"""Claim, send, and persist inspector credential email delivery."""

from app.database import get_connection
from app.services.email.resend import EmailDeliveryError, send_inspector_credentials_email


def deliver_inspector_credentials_email(user_id: int) -> bool:
    """Send one verified inspector's credentials; return False if already sent."""
    with get_connection() as connection:
        result = connection.execute(
            """UPDATE users
            SET credentials_email_claimed_at = clock_timestamp(),
                credentials_email_attempts = credentials_email_attempts + 1,
                credentials_email_last_error = NULL
            WHERE id = ?
                AND status = 'Verified'
                AND email <> ''
                AND username IS NOT NULL
                AND temp_password IS NOT NULL
                AND credentials_email_sent_at IS NULL
                AND (
                    credentials_email_claimed_at IS NULL
                    OR credentials_email_claimed_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
                )
            RETURNING id, name, email, username, temp_password,
                credentials_email_claimed_at""",
            (user_id,),
        )
        claimed = result.fetchone()
        if claimed is None:
            state = connection.execute(
                """SELECT status, email, username, temp_password,
                    credentials_email_sent_at, credentials_email_claimed_at
                FROM users WHERE id = ?""",
                (user_id,),
            ).fetchone()
            if state is None:
                raise EmailDeliveryError("Inspector not found.", status_code=404)
            if state["status"] != "Verified":
                raise EmailDeliveryError(
                    "Inspector must be verified before credentials can be emailed.",
                    status_code=409,
                )
            if not state["email"] or not state["username"] or not state["temp_password"]:
                raise EmailDeliveryError(
                    "Assign an email, username, and password before sending credentials.",
                    status_code=409,
                )
            if state["credentials_email_sent_at"] is not None:
                return False
            raise EmailDeliveryError(
                "A credentials email is already being sent. Try again shortly.",
                status_code=409,
            )

    try:
        send_inspector_credentials_email(
            recipient=claimed["email"],
            name=claimed["name"],
            username=claimed["username"],
            password=claimed["temp_password"],
        )
    except EmailDeliveryError as error:
        with get_connection() as connection:
            connection.execute(
                """UPDATE users
                SET credentials_email_claimed_at = NULL,
                    credentials_email_last_error = ?
                WHERE id = ? AND credentials_email_claimed_at = ?""",
                (str(error), user_id, claimed["credentials_email_claimed_at"]),
            )
        raise

    with get_connection() as connection:
        saved = connection.execute(
            """UPDATE users
            SET credentials_email_sent_at = CURRENT_TIMESTAMP,
                credentials_email_claimed_at = NULL,
                credentials_email_last_error = NULL
            WHERE id = ?
                AND credentials_email_claimed_at = ?
                AND email = ? AND username = ? AND temp_password = ?""",
            (
                user_id,
                claimed["credentials_email_claimed_at"],
                claimed["email"],
                claimed["username"],
                claimed["temp_password"],
            ),
        )
        if saved.rowcount == 0:
            raise EmailDeliveryError(
                "Inspector credentials changed during email delivery. Send the updated credentials again.",
                status_code=409,
            )
    return True
