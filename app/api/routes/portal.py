"""Portal-level demo data API."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.api.security import (
    require_active_inspector_id,
    require_authenticated_user,
    require_authority_officer,
)
from app.services import portal_service, reverse_geocode_service

router = APIRouter(tags=["Portal data"])


class PortalSettings(BaseModel):
    displayName: str = Field(min_length=1, max_length=100)
    oversightUnit: str = Field(min_length=1, max_length=150)
    criticalInspectionAlerts: bool
    automaticSynchronization: bool


@router.get(
    "/portal-data",
    response_model=dict,
    dependencies=[Depends(require_authority_officer)],
)
def get_portal_data():
    """Return the persisted fixture collections used by the authority UI."""
    return portal_service.get_portal_data()


@router.put(
    "/portal-data/settings",
    response_model=PortalSettings,
    dependencies=[Depends(require_authority_officer)],
)
def update_portal_settings(settings: PortalSettings):
    """Persist authority preferences in SQLite."""
    return portal_service.update_portal_settings(settings.model_dump())


@router.get("/media/{media_id}")
def get_evidence_media(
    media_id: str,
    claims: dict = Depends(require_authenticated_user),
):
    inspector_id = (
        require_active_inspector_id(claims)
        if claims["role"] == "inspector"
        else None
    )
    media = portal_service.get_evidence_media(media_id, inspector_id)
    if media is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence media not found")
    media_type, content = media
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/location/reverse", response_model=dict[str, str])
def reverse_geocode_location(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
):
    """Return a cached nearby address using OpenStreetMap Nominatim."""
    try:
        return reverse_geocode_service.reverse_geocode(latitude, longitude)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error