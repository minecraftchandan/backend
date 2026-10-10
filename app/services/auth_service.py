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
            """SELECT username, role, display_name, password_salt, password_hash
            FROM accounts WHERE username = ? AND role = ?""",
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

    user_id = None
    with get_connection() as connection:
        user_row = connection.execute(
            "SELECT id FROM users WHERE username = ?",
            (account["username"],),
        ).fetchone()
        if user_row:
            user_id = user_row["id"]

    return {
        "role": account["role"],
        "username": account["username"],
        "displayName": account["display_name"],
        "userId": user_id,
    }
