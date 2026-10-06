"""User (inspector) persistence service."""

from typing import Optional

from app.database import get_connection
from app.schemas.user import User


def get_all_users() -> list[User]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT id, name, designation, region FROM users ORDER BY id"
        ).fetchall()
    return [User.model_validate(dict(row)) for row in rows]


def get_user_by_id(user_id: int) -> Optional[User]:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, name, designation, region FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return User.model_validate(dict(row)) if row else None
