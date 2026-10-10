"""Shared credential helpers used by user registration and authentication."""

import hashlib
import re
import secrets


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000).hex()


def new_salt() -> bytes:
    return secrets.token_bytes(16)


def generate_username(name: str, connection) -> str:
    """Return a unique username derived from name, checking against accounts table."""
    base = re.sub(r"[^a-z0-9]+", ".", name.strip().lower()).strip(".")[:40] or "inspector"
    candidate = base
    suffix = 1
    while connection.execute(
        "SELECT 1 FROM accounts WHERE username = ?", (candidate,)
    ).fetchone():
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate
