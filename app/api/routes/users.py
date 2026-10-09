"""
Users API.

Returns backend-managed inspector profile data. User records are not an
authentication system.
"""

import psycopg

from fastapi import APIRouter, Depends, HTTPException

from app.api.security import require_authority_officer
from app.schemas.user import InspectorProfileUpdate, User
from app.services import user_service

router = APIRouter(tags=["Users"])


@router.get("/users", response_model=list[User])
def list_users():
    """Return all demo users (inspectors)."""
    return user_service.get_all_users()


@router.get("/users/{user_id}", response_model=User)
def get_user(user_id: int):
    """Return a single demo user by id, or 404 if not found."""
    user = user_service.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put(
    "/users/{user_id}/profile",
    response_model=User,
    dependencies=[Depends(require_authority_officer)],
)
def update_inspector_profile(user_id: int, payload: InspectorProfileUpdate):
    try:
        user = user_service.update_inspector_profile(user_id, payload)
    except psycopg.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="That official inspector ID is already assigned.",
        ) from error
    if user is None:
        raise HTTPException(status_code=404, detail="Inspector not found")
    return user
