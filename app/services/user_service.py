"""User (inspector) persistence service."""

from typing import Optional

from app.database import get_connection
from app.schemas.user import InspectorProfileUpdate, User, UserCreate, UserCredentialsUpdate, UserFullUpdate
from app.services.auth_helpers import hash_password, new_salt

_SELECT_COLS = """SELECT id, name, designation, region, specialization, email, phone,
    experience_years, bio, username, official_id, official_id_verified,
    department_unit, jurisdiction, qualifications, active, status,
    credentials_email_sent_at IS NOT NULL AS email_sent,
    (credentials_email_claimed_at IS NOT NULL
        AND credentials_email_claimed_at >= CURRENT_TIMESTAMP - INTERVAL '5 minutes')
        AS email_sending,
    credentials_email_attempts AS email_attempts,
    credentials_email_last_error AS email_error"""

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


def _replace_account_credentials(connection, old_username, username, display_name, password):
    if not username:
        raise ValueError("username_required")

    if username == old_username:
        if password is not None:
            salt = new_salt()
            connection.execute(
                "UPDATE accounts SET password_salt = ?, password_hash = ? WHERE username = ?",
                (salt.hex(), hash_password(password, salt), username),
            )
        return None

    existing_account = None
    if password is None:
        if not old_username:
            raise ValueError("credentials_required")
        existing_account = connection.execute(
            "SELECT role, password_salt, password_hash FROM accounts WHERE username = ?",
            (old_username,),
        ).fetchone()
        if existing_account is None:
            raise ValueError("credentials_required")

    if connection.execute(
        "SELECT username FROM accounts WHERE username = ?", (username,)
    ).fetchone() is not None:
        raise ValueError("username_exists")

    if password is not None:
        salt = new_salt()
        role = "inspector"
        password_salt = salt.hex()
        password_hash = hash_password(password, salt)
    else:
        role = existing_account["role"]
        password_salt = existing_account["password_salt"]
        password_hash = existing_account["password_hash"]

    connection.execute(
        """INSERT INTO accounts (username, role, display_name, password_salt, password_hash)
        VALUES (?, ?, ?, ?, ?)""",
        (username, role, display_name, password_salt, password_hash),
    )
    return old_username


def register_user(data: UserCreate) -> User:
    """Create a pending inspector. No account/username is created until approval."""
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE email = ?", (data.email,)
        ).fetchone()
        if existing is not None:
            raise ValueError("email_exists")
        connection.execute(
            """INSERT INTO users
            (name, designation, region, specialization, email, phone,
             experience_years, bio, qualifications, active, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, NULL)""",
            (
                data.name, data.designation, data.region, data.specialization,
                data.email, data.phone, data.experience_years, data.bio,
                data.qualifications,
            ),
        )
        row = connection.execute(
            f"{_SELECT_COLS} FROM users WHERE email = ? ORDER BY id DESC LIMIT 1",
            (data.email,),
        ).fetchone()
    return User.model_validate(dict(row))


def assign_credentials(user_id: int, data: UserCredentialsUpdate) -> Optional[User]:
    """Set username and password for an approved inspector, creating the account row."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT username, name FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return None
        old_username = _replace_account_credentials(
            connection, row["username"], data.username, row["name"], data.password
        )
        connection.execute(
            """UPDATE users SET username = ?, temp_password = ?,
                credentials_email_sent_at = NULL, credentials_email_claimed_at = NULL,
                credentials_email_attempts = 0, credentials_email_last_error = NULL
            WHERE id = ?""",
            (data.username, data.password, user_id),
        )
        if old_username:
            connection.execute("DELETE FROM accounts WHERE username = ?", (old_username,))
    return get_user_by_id(user_id, include_password=True)


def update_user_full(user_id: int, data: UserFullUpdate) -> Optional[User]:
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT username, temp_password, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if existing is None:
            return None
        new_username = data.username or existing["username"]
        new_temp_password = existing["temp_password"]
        old_username_to_delete = None
        if data.username is not None or data.password is not None:
            old_username_to_delete = _replace_account_credentials(
                connection,
                existing["username"],
                new_username,
                data.name,
                data.password,
            )
        if data.password is not None:
            new_temp_password = data.password
        reset_email_status = (
            data.email != existing["email"]
            or new_username != existing["username"]
            or data.password is not None
        )
        connection.execute(
            """UPDATE users SET name = ?, designation = ?, region = ?, specialization = ?,
                email = ?, phone = ?, experience_years = ?, bio = ?, qualifications = ?,
                username = ?, temp_password = ?,
                credentials_email_sent_at = CASE WHEN ? THEN NULL ELSE credentials_email_sent_at END,
                credentials_email_claimed_at = CASE WHEN ? THEN NULL ELSE credentials_email_claimed_at END,
                credentials_email_attempts = CASE WHEN ? THEN 0 ELSE credentials_email_attempts END,
                credentials_email_last_error = CASE WHEN ? THEN NULL ELSE credentials_email_last_error END
            WHERE id = ?""",
            (
                data.name, data.designation, data.region, data.specialization,
                data.email, data.phone, data.experience_years, data.bio,
                data.qualifications, new_username, new_temp_password,
                reset_email_status, reset_email_status, reset_email_status,
                reset_email_status, user_id,
            ),
        )
        if old_username_to_delete:
            connection.execute(
                "DELETE FROM accounts WHERE username = ?", (old_username_to_delete,)
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
                profile.jurisdiction, profile.region,
                profile.qualifications, profile.active, user_id,
            ),
        )
        if result.rowcount == 0:
            return None
    return get_user_by_id(user_id)
