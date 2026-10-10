"""Inspection record persistence and location-verification service."""

import base64
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg

from app.database import get_connection
from app.schemas.inspection import Inspection, InspectionCreate
from app.services import schedule_service
from app.services.geo import distance_m

_SELECT_COLS = """SELECT id, organization, location, date, time, inspector, status, notes,
    schedule_id, scheduled_date, scheduled_time, latitude, longitude,
    location_accuracy_m, location_captured_at, photo_captured_at, submitted_at,
    client_submission_id, location_distance_m, location_verified,
    location_check_status, photo_media_id"""


def get_all_inspections() -> list[Inspection]:
    with get_connection() as connection:
        rows = connection.execute(
            f"{_SELECT_COLS} FROM inspections ORDER BY date, time, id"
        ).fetchall()
    return [Inspection.model_validate(dict(row)) for row in rows]


def get_inspection_by_id(inspection_id: str) -> Optional[Inspection]:
    with get_connection() as connection:
        row = connection.execute(
            f"{_SELECT_COLS} FROM inspections WHERE id = ?", (inspection_id,)
        ).fetchone()
    return Inspection.model_validate(dict(row)) if row else None


def _fetch_by_submission_id(client_submission_id: str) -> Optional[Inspection]:
    with get_connection() as connection:
        row = connection.execute(
            f"{_SELECT_COLS} FROM inspections WHERE client_submission_id = ?",
            (client_submission_id,),
        ).fetchone()
    return Inspection.model_validate(dict(row)) if row else None


def delete_inspection(inspection_id: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT schedule_id, photo_media_id FROM inspections WHERE id = ?",
            (inspection_id,),
        ).fetchone()
        if row is None:
            return False
        connection.execute(
            "INSERT OR IGNORE INTO deleted_inspections (id) VALUES (?)", (inspection_id,)
        )
        connection.execute("DELETE FROM inspections WHERE id = ?", (inspection_id,))
        media_id = row["photo_media_id"]
        if media_id:
            connection.execute(
                """DELETE FROM evidence_media WHERE media_id = ?
                AND NOT EXISTS (SELECT 1 FROM inspections WHERE photo_media_id = ?)""",
                (media_id, media_id),
            )
        schedule_id = row["schedule_id"]
        if schedule_id:
            connection.execute(
                """UPDATE schedules SET status = 'Scheduled'
                WHERE id = ? AND NOT EXISTS (
                    SELECT 1 FROM inspections
                    WHERE schedule_id = ? AND client_submission_id IS NOT NULL
                )""",
                (schedule_id, schedule_id),
            )
    return True


def update_review_status(inspection_id: str, status: str) -> Optional[Inspection]:
    with get_connection() as connection:
        result = connection.execute(
            "UPDATE inspections SET status = ? WHERE id = ?", (status, inspection_id)
        )
        if result.rowcount == 0:
            return None
        row = connection.execute(
            f"{_SELECT_COLS} FROM inspections WHERE id = ?", (inspection_id,)
        ).fetchone()
    return Inspection.model_validate(dict(row)) if row else None


def create_inspection(data: InspectionCreate) -> Inspection:
    if data.client_submission_id:
        existing = _fetch_by_submission_id(data.client_submission_id)
        if existing:
            return existing

    photo_media_id = f"inspection-{uuid.uuid4().hex}" if data.photo_data_url else None
    fields = data.model_dump(exclude={"photo_data_url"})
    scheduled = schedule_service.get_schedule_by_id(data.schedule_id) if data.schedule_id else None
    submitted_utc = datetime.now(timezone.utc)
    submitted_local = submitted_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    fields.update({
        "date": submitted_local.date().isoformat(),
        "time": submitted_local.strftime("%I:%M %p"),
        "scheduled_date": scheduled.date if scheduled else data.scheduled_date,
        "scheduled_time": scheduled.time if scheduled else data.scheduled_time,
    })

    dist = None
    location_verified = None
    location_check_status = "not_configured"

    if data.latitude is None or data.longitude is None:
        location_check_status = "not_captured"
    elif (
        scheduled
        and scheduled.site_latitude is not None
        and scheduled.site_longitude is not None
        and scheduled.site_radius_m is not None
    ):
        dist = distance_m(data.latitude, data.longitude, scheduled.site_latitude, scheduled.site_longitude)
        accuracy = data.location_accuracy_m
        if accuracy is None:
            location_check_status = "inconclusive"
        elif dist + accuracy <= scheduled.site_radius_m:
            location_verified = True
            location_check_status = "verified"
        elif dist - accuracy > scheduled.site_radius_m:
            location_verified = False
            location_check_status = "outside_radius"
        else:
            location_check_status = "inconclusive"

    record = Inspection(
        id=f"REC-{uuid.uuid4().hex[:8].upper()}",
        **fields,
        photo_media_id=photo_media_id,
        submitted_at=submitted_utc.isoformat(),
        location_distance_m=round(dist, 1) if dist is not None else None,
        location_verified=location_verified,
        location_check_status=location_check_status,
    )

    try:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO inspections (
                    id, organization, location, date, time, inspector, status, notes,
                    schedule_id, scheduled_date, scheduled_time, latitude, longitude,
                    location_accuracy_m, location_captured_at, photo_captured_at,
                    submitted_at, client_submission_id, location_distance_m,
                    location_verified, location_check_status, photo_media_id
                ) VALUES (
                    :id, :organization, :location, :date, :time, :inspector, :status, :notes,
                    :schedule_id, :scheduled_date, :scheduled_time, :latitude, :longitude,
                    :location_accuracy_m, :location_captured_at, :photo_captured_at,
                    :submitted_at, :client_submission_id, :location_distance_m,
                    :location_verified, :location_check_status, :photo_media_id
                )""",
                record.model_dump(),
            )
            if data.photo_data_url:
                header, encoded = data.photo_data_url.split(",", 1)
                media_type = header.removeprefix("data:").removesuffix(";base64")
                connection.execute(
                    "INSERT INTO evidence_media (media_id, media_type, content) VALUES (?, ?, ?)",
                    (photo_media_id, media_type, base64.b64decode(encoded)),
                )
            if data.schedule_id:
                connection.execute(
                    "UPDATE schedules SET status = 'Completed' WHERE id = ?", (data.schedule_id,)
                )
    except psycopg.IntegrityError:
        if data.client_submission_id:
            existing = _fetch_by_submission_id(data.client_submission_id)
            if existing:
                return existing
        raise

    return record
