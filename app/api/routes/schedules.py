"""Inspection schedule API."""

from fastapi import APIRouter, HTTPException, Query

from app.schemas.schedule import ScheduleCreate, ScheduleItem
from app.services import schedule_service

router = APIRouter(tags=["Schedule"])


@router.get("/schedule", response_model=list[ScheduleItem])
def list_schedule():
    """Return all persisted inspection schedules."""
    return schedule_service.get_all_schedules()


@router.post("/schedule", response_model=ScheduleItem, status_code=201)
def create_schedule(payload: ScheduleCreate):
    """Create an assignment for a registered organization and inspector."""
    try:
        return schedule_service.create_scheduled_inspection(payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/schedule/generate", response_model=list[ScheduleItem])
def generate_schedule(
    count: int = Query(default=3, ge=1, le=20, description="How many demo entries to create"),
):
    """Generate `count` new random demo schedule entries and return them."""
    return schedule_service.generate_random_schedule(count)
