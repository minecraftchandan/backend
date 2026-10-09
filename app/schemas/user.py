"""
Pydantic schemas for users (inspectors).

These describe the shape of user data returned by the API. Records are
stored in PostgreSQL and include the inspector's operational profile.
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class InspectorProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    designation: str = Field(min_length=2, max_length=150)
    official_id: str = Field(min_length=1, max_length=80)
    department_unit: str = Field(min_length=2, max_length=150)
    jurisdiction: str = Field(min_length=2, max_length=150)
    active: bool

    @field_validator(
        "name",
        "designation",
        "official_id",
        "department_unit",
        "jurisdiction",
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
    official_id: Optional[str] = None
    department_unit: str
    jurisdiction: str
    active: bool
