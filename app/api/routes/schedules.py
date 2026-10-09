"""Inspection schedule API."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.security import require_authority_officer
from app.schemas.schedule import ScheduleCreate, ScheduleItem
from app.services import notification_service, schedule_service

router = APIRouter(tags=["Schedule"])


@router.get("/schedule", response_model=list[ScheduleItem])
def list_schedule():
    """Return all persisted inspection schedules."""
    return schedule_service.get_all_schedules()


@router.post(
    "/schedule",
    response_model=ScheduleItem,
    status_code=201,
    dependencies=[Depends(require_authority_officer)],
)
def create_schedule(payload: ScheduleCreate):
    """Create an assignment for a registered organization and inspector."""
    try:
        return schedule_service.create_scheduled_inspection(payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/schedule/generate",
    response_model=list[ScheduleItem],
    dependencies=[Depends(require_authority_officer)],
)
def generate_schedule(
    count: int = Query(default=3, ge=1, le=20, description="How many demo entries to create"),
):
    """Generate `count` new random demo schedule entries and return them."""
    try:
        return schedule_service.generate_random_schedule(count)
    except LookupError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/schedule/{schedule_id}/notification/retry",
    response_model=ScheduleItem,
    dependencies=[Depends(require_authority_officer)],
)
def retry_schedule_notification(schedule_id: str):
    """Retry a failed organization notification without changing the schedule."""
    try:
        notification_service.retry_schedule_notification(schedule_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    schedule = schedule_service.get_schedule_by_id(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule
