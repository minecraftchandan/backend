"""Credential verification for demo portal accounts."""

import hashlib
import hmac

from app.database import get_connection

ROLE_BY_PORTAL = {
    "Authority Officer": "authority",
    "Inspector": "inspector",
}


def authenticate(username: str, password: str, portal_role: str) -> dict | None:
    role = ROLE_BY_PORTAL.get(portal_role)
    if role is None:
        return None

    with get_connection() as connection:
        account = connection.execute(
            """SELECT a.username, a.role, a.display_name, a.password_salt, a.password_hash,
                u.id AS user_id, COALESCE(u.status, 'Pending') AS status,
                COALESCE(u.active, TRUE) AS active
            FROM accounts a
            LEFT JOIN users u ON u.username = a.username
            WHERE a.username = ? AND a.role = ?""",
            (username.strip().lower(), role),
        ).fetchone()

    if account is None:
        return None

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(account["password_salt"]),
        310_000,
    ).hex()
    if not hmac.compare_digest(password_hash, account["password_hash"]):
        return None

    user_id = account["user_id"]
    user_status = account["status"] if role == "inspector" else None
    if role == "inspector" and (user_id is None or not account["active"] or user_status == "Flagged"):
        return None

    session = {
        "role": account["role"],
        "username": account["username"],
        "displayName": account["display_name"],
        "userId": user_id,
    }
    if user_status is not None:
        session["status"] = user_status
        if user_status == "Pending":
            session["verificationMessage"] = (
                "Manual verification is in progress. Estimated completion: within 24 hours."
            )
    return session
