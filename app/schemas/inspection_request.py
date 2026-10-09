"""Department inspection-request schemas."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class InspectionRequestCreate(BaseModel):
    department: str = Field(min_length=2, max_length=150)
    requester_name: str = Field(min_length=2, max_length=150)
    requester_email: str = Field(
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    organization_id: str = Field(min_length=1, max_length=100)
    organization: str = Field(min_length=1, max_length=150)
    purpose: str = Field(min_length=10, max_length=2000)
    scope: str = Field(min_length=10, max_length=4000)
    urgency: Literal["Routine", "Time-sensitive", "Urgent"]

    @field_validator(
        "department",
        "requester_name",
        "requester_email",
        "organization_id",
        "organization",
        "purpose",
        "scope",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("purpose", "scope")
    @classmethod
    def require_meaningful_text(cls, value: str) -> str:
        if len(value) < 10:
            raise ValueError("Provide a meaningful purpose and scope.")
        return value


class InspectionRequest(BaseModel):
    id: str
    department: str
    requester_name: str
    requester_email: str
    requester_verified: bool = False
    organization_id: str
    organization: str
    purpose: str
    scope: str
    urgency: str
    status: Literal["Pending", "Approved", "Rejected"]
    created_at: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


class InspectionRequestReview(BaseModel):
    status: Literal["Approved", "Rejected"]
