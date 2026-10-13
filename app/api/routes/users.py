"""
Users API.

Returns backend-managed inspector profile data. User records are not an
authentication system.
"""

import psycopg

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.security import require_authority_officer, require_authenticated_user
from app.schemas.user import (
    InspectorProfileUpdate,
    User,
    UserCreate,
    UserCredentialsUpdate,
    UserFullUpdate,
    UserStatusUpdate,
)
from app.services import user_service

router = APIRouter(tags=["Users"])
public_router = APIRouter(tags=["Users"])


@public_router.post("/users/register", response_model=User, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate):
    try:
        return user_service.register_user(payload)
    except ValueError as error:
        if "email_exists" in str(error):
            raise HTTPException(status_code=409, detail="Email already registered.")
        raise HTTPException(status_code=422, detail=str(error)) from error
    except psycopg.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Email already registered.") from error


@router.get("/users", response_model=list[User], dependencies=[Depends(require_authority_officer)])
def list_users():
    return user_service.get_all_users(include_password=True)


@router.get("/users/me", response_model=User)
def get_current_user(claims: dict = Depends(require_authenticated_user)):
    if claims.get("uid") is None:
        raise HTTPException(status_code=404, detail="User not found")
    user = user_service.get_user_by_id(claims["uid"])
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/users/{user_id}", response_model=User)
def get_user(user_id: int, claims: dict = Depends(require_authority_officer)):
    user = user_service.get_user_by_id(user_id, include_password=True)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/users/{user_id}", response_model=User, dependencies=[Depends(require_authority_officer)])
def update_user_full(user_id: int, payload: UserFullUpdate):
    try:
        user = user_service.update_user_full(user_id, payload)
    except ValueError as error:
        if "username_exists" in str(error):
            raise HTTPException(status_code=409, detail="Username is already assigned.") from error
        raise HTTPException(status_code=422, detail=str(error)) from error
    except psycopg.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Username is already assigned.") from error
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put(
    "/users/{user_id}/credentials",
    response_model=User,
    dependencies=[Depends(require_authority_officer)],
)
def assign_inspector_credentials(user_id: int, payload: UserCredentialsUpdate):
    try:
        user = user_service.assign_credentials(user_id, payload)
    except ValueError as error:
        if "username_exists" in str(error):
            raise HTTPException(status_code=409, detail="Username is already assigned.") from error
        raise HTTPException(status_code=422, detail=str(error)) from error
    except psycopg.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Username is already assigned.") from error
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/users/{user_id}/status", response_model=User, dependencies=[Depends(require_authority_officer)])
def update_user_status(user_id: int, payload: UserStatusUpdate):
    user = user_service.update_user_status(user_id, payload.status)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_authority_officer)])
def delete_user(user_id: int):
    if not user_service.delete_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")


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
