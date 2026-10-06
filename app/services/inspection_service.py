"""Inspection record persistence and location-verification service."""

import base64
import uuid
from datetime import datetime, timedelta, timezone
from math import atan2, cos, radians, sin, sqrt
from typing import Optional

import psycopg

from app.database import get_connection
from app.schemas.inspection import Inspection, InspectionCreate
from app.services import schedule_service


def get_all_inspections() -> list[Inspection]:
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT id, organization, location, date, time, inspector, status, notes,
            schedule_id, scheduled_date, scheduled_time, latitude, longitude,
            location_accuracy_m, location_captured_at, photo_captured_at, submitted_at,
            client_submission_id,
            location_distance_m, location_verified, location_check_status, photo_media_id
            FROM inspections ORDER BY date, time, id"""
        ).fetchall()
    return [Inspection.model_validate(dict(row)) for row in rows]


def get_inspection_by_id(inspection_id: str) -> Optional[Inspection]:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT id, organization, location, date, time, inspector, status, notes,
            schedule_id, scheduled_date, scheduled_time, latitude, longitude,
            location_accuracy_m, location_captured_at, photo_captured_at, submitted_at,
            client_submission_id,
            location_distance_m, location_verified, location_check_status, photo_media_id
            FROM inspections WHERE id = ?""",
            (inspection_id,),
        ).fetchone()
    return Inspection.model_validate(dict(row)) if row else None


def delete_inspection(inspection_id: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT schedule_id, photo_media_id
            FROM inspections WHERE id = ?""",
            (inspection_id,),
        ).fetchone()
        if row is None:
            return False

        connection.execute(
            "INSERT OR IGNORE INTO deleted_inspections (id) VALUES (?)",
            (inspection_id,),
        )
        connection.execute("DELETE FROM inspections WHERE id = ?", (inspection_id,))
        media_id = row["photo_media_id"]
        if media_id:
            connection.execute(
                """DELETE FROM evidence_media WHERE media_id = ?
                AND NOT EXISTS (
                    SELECT 1 FROM inspections WHERE photo_media_id = ?
                )""",
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
            "UPDATE inspections SET status = ? WHERE id = ?",
            (status, inspection_id),
        )
        if result.rowcount == 0:
            return None
        row = connection.execute(
            """SELECT id, organization, location, date, time, inspector, status, notes,
            schedule_id, scheduled_date, scheduled_time, latitude, longitude,
            location_accuracy_m, location_captured_at, photo_captured_at, submitted_at,
            client_submission_id,
            location_distance_m, location_verified, location_check_status, photo_media_id
            FROM inspections WHERE id = ?""",
            (inspection_id,),
        ).fetchone()
    return Inspection.model_validate(dict(row)) if row else None


def create_inspection(data: InspectionCreate) -> Inspection:
    if data.client_submission_id:
        with get_connection() as connection:
            row = connection.execute(
                """SELECT id, organization, location, date, time, inspector, status, notes,
                schedule_id, scheduled_date, scheduled_time, latitude, longitude,
                location_accuracy_m, location_captured_at, photo_captured_at, submitted_at,
                client_submission_id,
                location_distance_m, location_verified, location_check_status, photo_media_id
                FROM inspections WHERE client_submission_id = ?""",
                (data.client_submission_id,),
            ).fetchone()
        if row:
            return Inspection.model_validate(dict(row))

    photo_media_id = f"inspection-{uuid.uuid4().hex}" if data.photo_data_url else None
    fields = data.model_dump(exclude={"photo_data_url"})
    scheduled = schedule_service.get_schedule_by_id(data.schedule_id) if data.schedule_id else None
    submitted_utc = datetime.now(timezone.utc)
    submitted_local = submitted_utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    scheduled_date = scheduled.date if scheduled else data.scheduled_date
    scheduled_time = scheduled.time if scheduled else data.scheduled_time
    fields.update(
        {
            "date": submitted_local.date().isoformat(),
            "time": submitted_local.strftime("%I:%M %p"),
            "scheduled_date": scheduled_date,
            "scheduled_time": scheduled_time,
        }
    )
    distance_m = None
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
        distance_m = _distance_m(
            data.latitude,
            data.longitude,
            scheduled.site_latitude,
            scheduled.site_longitude,
        )
        accuracy_m = data.location_accuracy_m
        if accuracy_m is None:
            location_check_status = "inconclusive"
        elif distance_m + accuracy_m <= scheduled.site_radius_m:
            location_verified = True
            location_check_status = "verified"
        elif distance_m - accuracy_m > scheduled.site_radius_m:
            location_verified = False
            location_check_status = "outside_radius"
        else:
            location_check_status = "inconclusive"

    record = Inspection(
        id=f"REC-{uuid.uuid4().hex[:8].upper()}",
        **fields,
        photo_media_id=photo_media_id,
        submitted_at=submitted_utc.isoformat(),
        location_distance_m=round(distance_m, 1) if distance_m is not None else None,
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
                    "UPDATE schedules SET status = 'Completed' WHERE id = ?",
                    (data.schedule_id,),
                )
    except psycopg.IntegrityError:
        if data.client_submission_id:
            with get_connection() as connection:
                row = connection.execute(
                    """SELECT id, organization, location, date, time, inspector, status, notes,
                    schedule_id, scheduled_date, scheduled_time, latitude, longitude,
                    location_accuracy_m, location_captured_at, photo_captured_at, submitted_at,
                    client_submission_id,
                    location_distance_m, location_verified, location_check_status, photo_media_id
                    FROM inspections WHERE client_submission_id = ?""",
                    (data.client_submission_id,),
                ).fetchone()
            if row:
                return Inspection.model_validate(dict(row))
        raise

    return record


def _distance_m(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    earth_radius_m = 6_371_000
    latitude_delta = radians(latitude_b - latitude_a)
    longitude_delta = radians(longitude_b - longitude_a)
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(radians(latitude_a))
        * cos(radians(latitude_b))
        * sin(longitude_delta / 2) ** 2
    )
    haversine = min(1, max(0, haversine))
    return earth_radius_m * 2 * atan2(sqrt(haversine), sqrt(1 - haversine))
