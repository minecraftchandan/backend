"""
Inspection records API.

Inspection submissions are persisted in SQLite. PostgreSQL/PostGIS can
replace the storage later without changing this API contract.
"""

from fastapi import APIRouter, HTTPException, status

from app.schemas.inspection import Inspection, InspectionCreate, InspectionReviewStatus
from app.services import inspection_service

router = APIRouter(tags=["Inspections"])


@router.get("/inspections", response_model=list[Inspection])
def list_inspections():
    """Return all demo inspection records."""
    return inspection_service.get_all_inspections()


@router.get("/inspections/{inspection_id}", response_model=Inspection)
def get_inspection(inspection_id: str):
    """Return a single inspection record by id, or 404 if not found."""
    record = inspection_service.get_inspection_by_id(inspection_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return record


@router.post("/inspections", response_model=Inspection, status_code=status.HTTP_201_CREATED)
def create_inspection(payload: InspectionCreate):
    """Create a new demo inspection record and return it with its id."""
    return inspection_service.create_inspection(payload)


@router.delete("/inspections/{inspection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inspection(inspection_id: str):
    """Delete an inspection and keep seeded records from being recreated."""
    deleted = inspection_service.delete_inspection(inspection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Inspection not found")


@router.put("/inspections/{inspection_id}/status", response_model=Inspection)
def update_inspection_status(inspection_id: str, payload: InspectionReviewStatus):
    """Persist an Authority review decision for an inspection record."""
    record = inspection_service.update_review_status(inspection_id, payload.status)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Inspection not found",
        )
    return record
