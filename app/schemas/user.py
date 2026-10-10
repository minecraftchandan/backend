"""
Pydantic schemas for users (inspectors).

These describe the shape of user data returned by the API. Records are
stored in PostgreSQL and include the inspector's operational profile.
"""

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(default="", max_length=30)
    designation: str = Field(min_length=2, max_length=150)
    specialization: str = Field(default="", max_length=150)
    region: str = Field(min_length=2, max_length=150)
    experience_years: Optional[int] = Field(default=None, ge=0, le=60)
    bio: str = Field(default="", max_length=2000)
    password: str = Field(min_length=6, max_length=128)

    @field_validator("name", "email", "designation", "specialization", "region", "phone", "bio", mode="before")
    @classmethod
    def strip_fields(cls, value):
        return value.strip() if isinstance(value, str) else value


class UserFullUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(default="", max_length=30)
    designation: str = Field(min_length=2, max_length=150)
    specialization: str = Field(default="", max_length=150)
    region: str = Field(min_length=2, max_length=150)
    experience_years: Optional[int] = Field(default=None, ge=0, le=60)
    bio: str = Field(default="", max_length=2000)
    username: Optional[str] = Field(default=None, max_length=80)
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)

    @field_validator("name", "email", "designation", "specialization", "region", "phone", "bio", mode="before")
    @classmethod
    def strip_fields(cls, value):
        return value.strip() if isinstance(value, str) else value


class UserStatusUpdate(BaseModel):
    status: Literal["Verified", "Flagged", "Pending"]


class InspectorProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    designation: str = Field(min_length=2, max_length=150)
    official_id: str = Field(min_length=1, max_length=80)
    official_id_verified: bool
    department_unit: str = Field(min_length=2, max_length=150)
    jurisdiction: str = Field(min_length=2, max_length=150)
    qualifications: str = Field(default="", max_length=1000)
    active: bool

    @field_validator(
        "name", "designation", "official_id", "department_unit", "jurisdiction", "qualifications",
        mode="before",
    )
    @classmethod
    def strip_profile_fields(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("name", "designation", "official_id", "department_unit", "jurisdiction")
    @classmethod
    def require_nonempty_profile_fields(cls, value: str) -> str:
        if not value:
            raise ValueError("Inspector profile fields must not be empty.")
        return value


class User(BaseModel):
    id: int
    name: str
    designation: str
    region: str
    specialization: str = ""
    email: str = ""
    phone: str = ""
    experience_years: Optional[int] = None
    bio: str = ""
    username: Optional[str] = None
    # temp_password is only populated for authority officer responses
    password: Optional[str] = None
    official_id: Optional[str] = None
    official_id_verified: bool = False
    department_unit: str = ""
    jurisdiction: str = ""
    qualifications: str = ""
    active: bool = True
    status: Optional[str] = None
