"""User (inspector) persistence service."""

from typing import Optional

from app.database import get_connection
from app.schemas.user import InspectorProfileUpdate, User


def get_all_users() -> list[User]:
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT id, name, designation, region, official_id,
                official_id_verified, department_unit, jurisdiction,
                qualifications, active
            FROM users ORDER BY id"""
        ).fetchall()
    return [User.model_validate(dict(row)) for row in rows]


def get_user_by_id(user_id: int) -> Optional[User]:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT id, name, designation, region, official_id,
                official_id_verified, department_unit, jurisdiction,
                qualifications, active
            FROM users WHERE id = ?""",
            (user_id,),
        ).fetchone()
    return User.model_validate(dict(row)) if row else None


def update_inspector_profile(
    user_id: int,
    profile: InspectorProfileUpdate,
) -> Optional[User]:
    with get_connection() as connection:
        result = connection.execute(
            """UPDATE users
            SET name = ?, designation = ?, official_id = ?, official_id_verified = ?,
                department_unit = ?, jurisdiction = ?, region = ?, qualifications = ?,
                active = ?
            WHERE id = ?""",
            (
                profile.name,
                profile.designation,
                profile.official_id,
                profile.official_id_verified,
                profile.department_unit,
                profile.jurisdiction,
                profile.jurisdiction,
                profile.qualifications,
                profile.active,
                user_id,
            ),
        )
        if result.rowcount == 0:
            return None
    return get_user_by_id(user_id)
