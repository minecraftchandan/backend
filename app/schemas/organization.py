"""Organization registry schemas."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    location: str = Field(min_length=2, max_length=150)
    address: str = Field(min_length=5, max_length=300)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_m: Optional[float] = Field(default=None, gt=0, le=100_000)


class OrganizationVerificationUpdate(BaseModel):
    verification: Literal["Verified", "Flagged"]


class Organization(BaseModel):
    id: str
    name: str
    reg: str
    location: str
    address: str
    last: str
    next: str
    verification: str
    risk: str
    count: int
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_m: Optional[float] = None