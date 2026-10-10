"""Department inspection-request schemas."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class NewOrganizationData(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    location: str = Field(default="", max_length=150)
    address: str = Field(default="", max_length=300)
    contact_person: str = Field(default="", max_length=150)
    contact_email: str = Field(default="", max_length=254)
    contact_phone: str = Field(default="", max_length=50)


class InspectionRequestCreate(BaseModel):
    department: str = Field(min_length=2, max_length=150)
    # frontend sends "contact" for the requester's contact info
    contact: str = Field(default="", max_length=254, alias="contact")
    requester_name: str = Field(default="", min_length=0, max_length=150)
    requester_email: str = Field(default="", max_length=254, pattern=r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$")
    organization_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    organization: str = Field(min_length=1, max_length=150)
    new_organization: Optional[str] = Field(default=None, max_length=500)
    # frontend sends "proposed_scope" and "priority"
    purpose: str = Field(default="", min_length=0, max_length=2000)
    proposed_scope: str = Field(default="", max_length=4000, alias="proposed_scope")
    priority: str = Field(default="Routine", max_length=50, alias="priority")
    # legacy fields kept for backward compat
    scope: str = Field(default="", max_length=4000)
    urgency: Literal["Routine", "Time-sensitive", "Urgent"] = "Routine"

    model_config = {"populate_by_name": True}

    @field_validator("department", "organization", "purpose", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("scope", "proposed_scope")
    @classmethod
    def require_meaningful_scope(cls, value: str) -> str:
        if value and len(value.strip()) < 10:
            raise ValueError("Scope must be at least 10 characters if provided.")
        return value


class InspectionRequest(BaseModel):
    id: str
    department: str
    contact: str = ""
    requester_name: str = ""
    requester_email: str = ""
    requester_verified: bool = False
    organization_id: Optional[str] = None
    organization: str
    new_organization: Optional[Any] = None
    purpose: str = ""
    proposed_scope: str = ""
    priority: str = "Routine"
    # kept for consumers that still read these
    scope: str = ""
    urgency: str = "Routine"
    status: Literal["Pending", "Approved", "Rejected"]
    created_at: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


class InspectionRequestReview(BaseModel):
    status: Literal["Approved", "Rejected", "Flagged"]
