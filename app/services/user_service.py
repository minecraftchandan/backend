"""User (inspector) persistence service."""

import secrets
from typing import Optional

from app.database import get_connection
from app.schemas.user import InspectorProfileUpdate, User, UserCreate, UserFullUpdate
from app.services.auth_helpers import generate_username, hash_password

_SELECT_COLS = """SELECT id, name, designation, region, specialization, email, phone,
    experience_years, bio, username, official_id, official_id_verified,
    department_unit, jurisdiction, qualifications, active, status"""

_SELECT_COLS_WITH_PASS = _SELECT_COLS + ", temp_password AS password"


def _row_to_user(row: dict, include_password: bool = False) -> User:
    data = dict(row)
    if not include_password:
        data.pop("password", None)
    return User.model_validate(data)


def get_all_users(include_password: bool = False) -> list[User]:
    cols = _SELECT_COLS_WITH_PASS if include_password else _SELECT_COLS
    with get_connection() as connection:
        rows = connection.execute(f"{cols} FROM users ORDER BY id").fetchall()
    return [_row_to_user(dict(row), include_password) for row in rows]


def get_user_by_id(user_id: int, include_password: bool = False) -> Optional[User]:
    cols = _SELECT_COLS_WITH_PASS if include_password else _SELECT_COLS
    with get_connection() as connection:
        row = connection.execute(f"{cols} FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(dict(row), include_password) if row else None


def register_user(data: UserCreate) -> User:
    salt = secrets.token_bytes(16)
    password_hash = hash_password(data.password, salt)
    with get_connection() as connection:
        username = generate_username(data.name, connection)
        connection.execute(
            """INSERT INTO users
            (name, designation, region, specialization, email, phone,
             experience_years, bio, username, temp_password,
             department_unit, jurisdiction, active, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, 'Pending')""",
            (
                data.name, data.designation, data.region, data.specialization,
                data.email, data.phone, data.experience_years, data.bio,
                username, data.password,
            ),
        )
        connection.execute(
            """INSERT INTO accounts (username, role, display_name, password_salt, password_hash)
            VALUES (?, 'inspector', ?, ?, ?)""",
            (username, data.name, salt.hex(), password_hash),
        )
        row = connection.execute(
            f"{_SELECT_COLS} FROM users WHERE username = ?", (username,)
        ).fetchone()
    return User.model_validate(dict(row))


def update_user_full(user_id: int, data: UserFullUpdate) -> Optional[User]:
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT username, temp_password FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if existing is None:
            return None
        new_username = data.username or existing["username"]
        new_temp_password = existing["temp_password"]
        if data.password:
            salt = secrets.token_bytes(16)
            password_hash = hash_password(data.password, salt)
            new_temp_password = data.password
            connection.execute(
                "UPDATE accounts SET password_salt = ?, password_hash = ? WHERE username = ?",
                (salt.hex(), password_hash, existing["username"]),
            )
            if new_username != existing["username"]:
                connection.execute(
                    "UPDATE accounts SET username = ? WHERE username = ?",
                    (new_username, existing["username"]),
                )
        connection.execute(
            """UPDATE users SET name = ?, designation = ?, region = ?, specialization = ?,
                email = ?, phone = ?, experience_years = ?, bio = ?,
                username = ?, temp_password = ?
            WHERE id = ?""",
            (
                data.name, data.designation, data.region, data.specialization,
                data.email, data.phone, data.experience_years, data.bio,
                new_username, new_temp_password, user_id,
            ),
        )
    return get_user_by_id(user_id, include_password=True)


def update_user_status(user_id: int, status: str) -> Optional[User]:
    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE users SET status = ? WHERE id = ?", (status, user_id)
        )
        if cursor.rowcount == 0:
            return None
    return get_user_by_id(user_id)


def delete_user(user_id: int) -> bool:
    with get_connection() as connection:
        row = connection.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return False
        connection.execute("DELETE FROM accounts WHERE username = ?", (row["username"],))
        cursor = connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cursor.rowcount > 0


def update_inspector_profile(user_id: int, profile: InspectorProfileUpdate) -> Optional[User]:
    with get_connection() as connection:
        result = connection.execute(
            """UPDATE users
            SET name = ?, designation = ?, official_id = ?, official_id_verified = ?,
                department_unit = ?, jurisdiction = ?, region = ?, qualifications = ?,
                active = ?
            WHERE id = ?""",
            (
                profile.name, profile.designation, profile.official_id,
                profile.official_id_verified, profile.department_unit,
                profile.jurisdiction, profile.jurisdiction,
                profile.qualifications, profile.active, user_id,
            ),
        )
        if result.rowcount == 0:
            return None
    return get_user_by_id(user_id)
