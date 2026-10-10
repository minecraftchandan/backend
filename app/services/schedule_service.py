"""Inspection schedule queries and creation."""

import json
import os
import uuid
from datetime import datetime

from app.database import get_connection
from app.schemas.schedule import ScheduleCreate, ScheduleItem
from app.services import notification_service
from app.services.schedule_demo import generate_random_schedule  # re-exported for routes

_SCHEDULE_SELECT = """SELECT s.id, s.organization, s.location, s.date, s.time,
    COALESCE(u.name, s.inspector) AS inspector, s.status,
    s.site_latitude, s.site_longitude, s.site_radius_m,
    s.purpose, s.scope, s.inspection_request_id,
    s.organization_notified, s.notification_status, s.notification_error,
    COALESCE(u.id, s.inspector_id) AS inspector_id,
    u.designation AS inspector_designation,
    u.official_id AS inspector_official_id,
    COALESCE(u.official_id_verified, FALSE) AS inspector_official_id_verified,
    COALESCE(u.qualifications, '') AS inspector_qualifications
FROM schedules s
LEFT JOIN users u ON u.id = COALESCE(
    s.inspector_id,
    (SELECT id FROM users WHERE name = s.inspector ORDER BY id LIMIT 1)
)"""


def _with_site_location(item: ScheduleItem) -> ScheduleItem:
    configured_sites = json.loads(os.getenv("SITE_LOCATIONS_JSON", "{}"))
    site = configured_sites.get(item.organization, {})
    return item.model_copy(update={
        "site_latitude": site.get("latitude", item.site_latitude),
        "site_longitude": site.get("longitude", item.site_longitude),
        "site_radius_m": site.get("radius_m", item.site_radius_m),
    })


def get_all_schedules() -> list[ScheduleItem]:
    with get_connection() as connection:
        rows = connection.execute(f"{_SCHEDULE_SELECT} ORDER BY s.date, s.time").fetchall()
    return [_with_site_location(ScheduleItem.model_validate(dict(row))) for row in rows]


def get_schedule_by_id(schedule_id: str) -> ScheduleItem | None:
    with get_connection() as connection:
        row = connection.execute(
            f"{_SCHEDULE_SELECT} WHERE s.id = ?", (schedule_id,)
        ).fetchone()
    item = ScheduleItem.model_validate(dict(row)) if row else None
    return _with_site_location(item) if item else None


def create_scheduled_inspection(payload: ScheduleCreate) -> ScheduleItem:
    scheduled_at = datetime.combine(payload.date, payload.time)
    if scheduled_at <= datetime.now():
        raise ValueError("Inspection date and time must be in the future.")

    scheduled_time = scheduled_at.strftime("%I:%M %p")

    with get_connection() as connection:
        organization = connection.execute(
            "SELECT id, name, location, address, latitude, longitude, radius_m FROM organizations WHERE id = ?",
            (payload.organization_id,),
        ).fetchone()
        if organization is None:
            raise LookupError("The selected organization is no longer registered.")

        inspector = connection.execute(
            "SELECT id, name, designation, official_id, official_id_verified, qualifications FROM users WHERE id = ? AND active = TRUE",
            (payload.inspector_id,),
        ).fetchone()
        if inspector is None:
            raise LookupError("The selected inspector is not registered and active.")
        if not inspector["official_id"] or not inspector["official_id"].strip():
            raise ValueError("The selected inspector must have an official ID on their profile before scheduling.")
        if (
            os.getenv("APP_ENV", "development").strip().lower() == "production"
            and (
                inspector["official_id"].startswith(("DEMO-", "STAGING-"))
                or not inspector["official_id_verified"]
            )
        ):
            raise ValueError("Production scheduling requires an officer-verified official inspector ID.")

        if payload.inspection_request_id is not None:
            request = connection.execute(
                "SELECT organization_id, status FROM inspection_requests WHERE id = ?",
                (payload.inspection_request_id,),
            ).fetchone()
            if request is None:
                raise LookupError("The linked inspection request could not be found.")
            if request["organization_id"] != payload.organization_id:
                raise ValueError("The linked request is for a different organization.")
            if request["status"] != "Approved":
                raise ValueError("Only an approved inspection request can be scheduled.")

        conflict = connection.execute(
            """SELECT id FROM schedules
            WHERE date = ? AND time = ?
            AND (inspector_id = ? OR (inspector_id IS NULL AND inspector = ?))
            AND lower(status) != 'completed' LIMIT 1""",
            (payload.date.isoformat(), scheduled_time, inspector["id"], inspector["name"]),
        ).fetchone()
        if conflict is not None:
            raise ValueError("This inspector already has an inspection scheduled at that date and time.")

        item = ScheduleItem(
            id=f"SCH-{uuid.uuid4().hex[:8].upper()}",
            organization=organization["name"],
            location=organization["address"],
            date=payload.date.isoformat(),
            time=scheduled_time,
            inspector=inspector["name"],
            status="Scheduled",
            site_latitude=organization["latitude"],
            site_longitude=organization["longitude"],
            site_radius_m=organization["radius_m"],
            purpose=payload.purpose,
            scope=payload.scope,
            inspector_id=inspector["id"],
            inspector_designation=inspector["designation"],
            inspector_official_id=inspector["official_id"],
            inspector_official_id_verified=inspector["official_id_verified"],
            inspector_qualifications=inspector["qualifications"] or "",
            inspection_request_id=payload.inspection_request_id,
            organization_notified=False,
            notification_status="pending" if payload.notify_organization else "not_requested",
        )
        connection.execute(
            """INSERT INTO schedules
            (id, organization, location, date, time, inspector, status,
            site_latitude, site_longitude, site_radius_m, purpose, scope,
            inspector_id, inspection_request_id, notification_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id, item.organization, item.location, item.date, item.time,
                item.inspector, item.status, item.site_latitude, item.site_longitude,
                item.site_radius_m, item.purpose, item.scope, item.inspector_id,
                item.inspection_request_id, item.notification_status,
            ),
        )
        if payload.notify_organization:
            connection.execute(
                "INSERT INTO inspection_notification_outbox (schedule_id, status) VALUES (?, 'pending')",
                (item.id,),
            )

    if payload.notify_organization:
        item = item.model_copy(update=notification_service.deliver_schedule_notification(item.id))
    return item
