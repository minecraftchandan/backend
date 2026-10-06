"""
Pydantic schemas for inspection records.

An inspection record represents a visit that has been (or is being)
carried out. `InspectionCreate` is what the API accepts when a new record
is submitted; `Inspection` is what the API returns, with a server-assigned
id. Records are persisted in SQLite and can move to PostgreSQL/PostGIS
without changing this contract.
"""

import base64
import binascii
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class InspectionBase(BaseModel):
    organization: str
    location: str
    date: str  # YYYY-MM-DD
    time: str  # e.g. "10:30 AM"
    inspector: str
    status: str = "Submitted"  # e.g. "Submitted", "Verified"
    notes: Optional[str] = None
    schedule_id: Optional[str] = None
    scheduled_date: Optional[str] = None
    scheduled_time: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    location_accuracy_m: Optional[float] = Field(default=None, ge=0)
    location_captured_at: Optional[str] = None
    photo_captured_at: Optional[str] = None
    client_submission_id: Optional[str] = Field(default=None, max_length=100)


class InspectionCreate(InspectionBase):
    """Fields required to create a new inspection record."""

    photo_data_url: Optional[str] = Field(default=None, max_length=6_000_000)

    @field_validator("photo_data_url")
    @classmethod
    def validate_photo_data_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        header, separator, encoded = value.partition(",")
        media_type = header.removeprefix("data:").removesuffix(";base64")
        if not separator or media_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("Photo evidence must be a base64 JPEG, PNG, or WebP image.")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("Photo evidence is not valid base64 data.") from error
        if len(content) > 4_000_000:
            raise ValueError("Photo evidence must be 4 MB or smaller.")
        return value


class Inspection(InspectionBase):
    """An inspection record as returned by the API, with its id."""

    id: str
    photo_media_id: Optional[str] = None
    submitted_at: Optional[str] = None
    location_distance_m: Optional[float] = None
    location_verified: Optional[bool] = None
    location_check_status: Optional[str] = None


class InspectionReviewStatus(BaseModel):
    status: Literal["Verified", "Flagged"]
