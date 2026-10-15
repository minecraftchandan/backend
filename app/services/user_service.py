"""User (inspector) persistence service."""

from typing import Optional

from app.database import get_connection
from app.schemas.user import InspectorProfileUpdate, User, UserCreate, UserFullUpdate
from app.services.auth_helpers import hash_password, new_salt

_SELECT_COLS = """SELECT id, name, designation, region, specialization, email, phone,
    experience_years, bio, username, official_id, official_id_verified,
    department_unit, jurisdiction, qualifications, active,
    COALESCE(status, 'Pending') AS status"""


def _row_to_user(row: dict) -> User:
    return User.model_validate(dict(row))


def get_all_users() -> list[User]:
    with get_connection() as connection:
        rows = connection.execute(f"{_SELECT_COLS} FROM users ORDER BY id").fetchall()
    return [_row_to_user(dict(row)) for row in rows]


def get_user_by_id(user_id: int) -> Optional[User]:
    with get_connection() as connection:
        row = connection.execute(f"{_SELECT_COLS} FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(dict(row)) if row else None


def register_user(data: UserCreate) -> User:
    """Create an inspector account that can sign in while pending verification."""
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE email = ?", (data.email,)
        ).fetchone()
        if existing is not None:
            raise ValueError("email_exists")
        existing = connection.execute(
            "SELECT username FROM accounts WHERE username = ?", (data.username,)
        ).fetchone()
        if existing is not None:
            raise ValueError("username_exists")

        salt = new_salt()
        connection.execute(
            """INSERT INTO accounts (username, role, display_name, password_salt, password_hash)
            VALUES (?, 'inspector', ?, ?, ?)""",
            (data.username, data.name, salt.hex(), hash_password(data.password, salt)),
        )
        connection.execute(
            """INSERT INTO users
            (username, name, designation, region, specialization, email, phone,
             experience_years, bio, qualifications, active, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, 'Pending')""",
            (
                data.username, data.name, data.designation, data.region,
                data.specialization, data.email, data.phone,
                data.experience_years, data.bio, data.qualifications,
            ),
        )
        row = connection.execute(
            f"{_SELECT_COLS} FROM users WHERE username = ?",
            (data.username,),
        ).fetchone()
    return User.model_validate(dict(row))


def update_user_full(user_id: int, data: UserFullUpdate) -> Optional[User]:
    with get_connection() as connection:
        updated = connection.execute(
            """UPDATE users SET name = ?, designation = ?, region = ?, specialization = ?,
                email = ?, phone = ?, experience_years = ?, bio = ?, qualifications = ?
            WHERE id = ?""",
            (
                data.name, data.designation, data.region, data.specialization,
                data.email, data.phone, data.experience_years, data.bio,
                data.qualifications, user_id,
            ),
        )
        if updated.rowcount == 0:
            return None
        connection.execute(
            """UPDATE accounts SET display_name = ?
            WHERE username = (SELECT username FROM users WHERE id = ?)""",
            (data.name, user_id),
        )
    return get_user_by_id(user_id)


def update_user_status(user_id: int, status: str) -> Optional[User]:
    with get_connection() as connection:
        if status == "Verified":
            credentials = connection.execute(
                """SELECT accounts.username
                FROM users
                JOIN accounts ON accounts.username = users.username
                WHERE users.id = ? AND accounts.role = 'inspector'""",
                (user_id,),
            ).fetchone()
            if credentials is None:
                raise ValueError("inspector_credentials_missing")
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
        if row["username"]:
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
