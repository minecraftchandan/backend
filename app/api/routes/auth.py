"""Portal login endpoint."""

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.security import issue_user_access_token
from app.services.auth_service import authenticate

router = APIRouter(tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)
    portal_role: Literal["Authority Officer", "Inspector"]


@router.post("/auth/login")
def login(payload: LoginRequest):
    session = authenticate(payload.username, payload.password, payload.portal_role)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password for the selected portal",
        )

    access_token, expires_at = issue_user_access_token(
        session["username"], session["role"], session.get("userId")
    )
    session["accessToken"] = access_token
    session["tokenType"] = "Bearer"
    session["expiresAt"] = expires_at * 1000
    return session