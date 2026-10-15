"""
Inspection records API.

Inspection submissions are persisted in SQLite. PostgreSQL/PostGIS can
replace the storage later without changing this API contract.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.security import (
    require_active_inspector_id,
    require_authenticated_user,
    require_authority_officer,
)
from app.schemas.inspection import Inspection, InspectionCreate, InspectionReviewStatus
from app.services import schedule_service
from app.services import inspection_service

router = APIRouter(tags=["Inspections"])


@router.get("/inspections", response_model=list[Inspection])
def list_inspections(claims: dict = Depends(require_authenticated_user)):
    """Return all records to authorities and assigned records to inspectors."""
    if claims["role"] == "authority":
        return inspection_service.get_all_inspections()
    inspector_id = require_active_inspector_id(claims)
    return inspection_service.get_inspections_for_inspector(inspector_id)


@router.get("/inspections/{inspection_id}", response_model=Inspection)
def get_inspection(inspection_id: str, claims: dict = Depends(require_authenticated_user)):
    """Return a record only to its assigned inspector or an Authority Officer."""
    if claims["role"] == "authority":
        record = inspection_service.get_inspection_by_id(inspection_id)
    else:
        inspector_id = require_active_inspector_id(claims)
        record = inspection_service.get_inspection_by_id_for_inspector(
            inspection_id,
            inspector_id,
        )
    if record is None:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return record


@router.post("/inspections", response_model=Inspection, status_code=status.HTTP_201_CREATED)
def create_inspection(
    payload: InspectionCreate,
    claims: dict = Depends(require_authenticated_user),
):
    """Create an inspection record and validate inspector schedule ownership."""
    if claims["role"] == "inspector":
        inspector_id = require_active_inspector_id(claims)
        if not payload.schedule_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="An assigned schedule is required to submit an inspection.",
            )
        schedule = schedule_service.get_schedule_by_id(payload.schedule_id)
        if schedule is None or schedule.inspector_id != inspector_id:
            raise HTTPException(status_code=404, detail="Assigned schedule not found")
        payload = payload.model_copy(update={
            "organization": schedule.organization,
            "location": schedule.location,
            "date": schedule.date,
            "time": schedule.time,
            "inspector": schedule.inspector,
            "scheduled_date": schedule.date,
            "scheduled_time": schedule.time,
        })
    return inspection_service.create_inspection(payload)


@router.delete(
    "/inspections/{inspection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_authority_officer)],
)
def delete_inspection(inspection_id: str):
    """Delete an inspection and keep seeded records from being recreated."""
    deleted = inspection_service.delete_inspection(inspection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Inspection not found")


@router.put(
    "/inspections/{inspection_id}/status",
    response_model=Inspection,
    dependencies=[Depends(require_authority_officer)],
)
def update_inspection_status(inspection_id: str, payload: InspectionReviewStatus):
    """Persist an Authority review decision for an inspection record."""
    record = inspection_service.update_review_status(inspection_id, payload.status)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Inspection not found",
        )
    return record
