"""
Pydantic schemas for the inspection schedule.

A schedule item represents an inspection that has been assigned to an
inspector but not necessarily carried out yet. Records are persisted in
PostgreSQL by the schedule service.
"""

import re
from datetime import date, time
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ScheduleCreate(BaseModel):
    organization_id: str = Field(min_length=1, max_length=100)
    inspector_id: int = Field(ge=1)
    date: date
    time: time
    purpose: str = Field(min_length=10, max_length=2000)
    scope: str = Field(min_length=10, max_length=4000)
    inspection_request_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    notify_organization: bool = True

    @field_validator("time", mode="before")
    @classmethod
    def validate_time_format(cls, value):
        if isinstance(value, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) is None:
            raise ValueError("Time must use the HH:MM format.")
        return value

    @field_validator("purpose", "scope")
    @classmethod
    def require_meaningful_text(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 10:
            raise ValueError("Provide a meaningful purpose and scope.")
        return normalized

    @field_validator("time")
    @classmethod
    def require_minute_precision(cls, value: time) -> time:
        if value.second or value.microsecond:
            raise ValueError("Time must use HH:MM precision.")
        return value


class ScheduleItem(BaseModel):
    id: str
    organization: str
    location: str
    date: str  # YYYY-MM-DD
    time: str  # e.g. "10:30 AM"
    inspector: str
    status: str  # e.g. "Scheduled", "In Progress", "Completed", "Missed"
    site_latitude: Optional[float] = None
    site_longitude: Optional[float] = None
    site_radius_m: Optional[float] = None
    purpose: Optional[str] = None
    scope: Optional[str] = None
    inspector_id: Optional[int] = None
    inspector_designation: Optional[str] = None
    inspector_official_id: Optional[str] = None
    inspection_request_id: Optional[str] = None
    organization_notified: bool = False
    notification_status: str = "not_requested"
    notification_error: Optional[str] = None
