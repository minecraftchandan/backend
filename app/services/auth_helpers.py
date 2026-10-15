"""Shared credential helpers used by user registration and authentication."""

import hashlib
import secrets


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000).hex()


def new_salt() -> bytes:
    return secrets.token_bytes(16)
