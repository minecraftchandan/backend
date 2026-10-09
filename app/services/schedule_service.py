"""
Inspection schedule service.

`generate_random_schedule` creates and persists demo schedule entries for
the Inspector Portal.
"""

import json
import os
import random
import uuid
from datetime import date, datetime, timedelta
from app.database import DEMO_SITE_COORDINATES, get_connection
from app.schemas.schedule import ScheduleCreate, ScheduleItem
from app.services import notification_service

_DEMO_ORGANIZATIONS = [
    ("Asha Bal Vikas Sanstha", "Kothrud, Pune"),
    ("Sanjeevani Old Age Support Trust", "Hadapsar, Pune"),
    ("Prerna Mahila Sangh", "Shivaji Nagar, Pune"),
    ("Gramin Shiksha Kendra", "Wagholi, Pune"),
    ("Nirmal Jeevan Foundation", "Kondhwa, Pune"),
    ("Disha Punarvasan Kendra", "Aundh, Pune"),
]

_DEMO_TIMES = ["09:30 AM", "10:30 AM", "11:00 AM", "02:00 PM", "03:30 PM"]

def get_all_schedules() -> list[ScheduleItem]:
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT s.id, s.organization, s.location, s.date, s.time,
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
            )
            ORDER BY s.date, s.time"""
        ).fetchall()
    return [_with_site_location(ScheduleItem.model_validate(dict(row))) for row in rows]


def get_schedule_by_id(schedule_id: str) -> ScheduleItem | None:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT s.id, s.organization, s.location, s.date, s.time,
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
            )
            WHERE s.id = ?""",
            (schedule_id,),
        ).fetchone()
    item = ScheduleItem.model_validate(dict(row)) if row else None
    return _with_site_location(item) if item else None


def _with_site_location(item: ScheduleItem) -> ScheduleItem:
    configured_sites = json.loads(os.getenv("SITE_LOCATIONS_JSON", "{}"))
    site = configured_sites.get(item.organization, {})
    return item.model_copy(
        update={
            "site_latitude": site.get("latitude", item.site_latitude),
            "site_longitude": site.get("longitude", item.site_longitude),
            "site_radius_m": site.get("radius_m", item.site_radius_m),
        }
    )


def create_scheduled_inspection(payload: ScheduleCreate) -> ScheduleItem:
    scheduled_at = datetime.combine(payload.date, payload.time)
    if scheduled_at <= datetime.now():
        raise ValueError("Inspection date and time must be in the future.")

    scheduled_time = scheduled_at.strftime("%I:%M %p")

    with get_connection() as connection:
        organization = connection.execute(
            """SELECT id, name, location, address, latitude, longitude, radius_m
            FROM organizations WHERE id = ?""",
            (payload.organization_id,),
        ).fetchone()
        if organization is None:
            raise LookupError("The selected organization is no longer registered.")

        inspector = connection.execute(
            """SELECT id, name, designation, official_id, official_id_verified,
                qualifications
            FROM users WHERE id = ? AND active = TRUE""",
            (payload.inspector_id,),
        ).fetchone()
        if inspector is None:
            raise LookupError("The selected inspector is not registered and active.")
        if not inspector["official_id"] or not inspector["official_id"].strip():
            raise ValueError(
                "The selected inspector must have an official ID on their profile before scheduling."
            )
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
                """SELECT organization_id, status FROM inspection_requests
                WHERE id = ?""",
                (payload.inspection_request_id,),
            ).fetchone()
            if request is None:
                raise LookupError("The linked inspection request could not be found.")
            if request["organization_id"] != payload.organization_id:
                raise ValueError("The linked request is for a different organization.")
            if request["status"] != "Approved":
                raise ValueError("Only an approved inspection request can be scheduled.")

        inspector_conflict = connection.execute(
            """SELECT id FROM schedules
            WHERE date = ? AND time = ?
            AND (inspector_id = ? OR (inspector_id IS NULL AND inspector = ?))
            AND lower(status) != 'completed' LIMIT 1""",
            (
                payload.date.isoformat(),
                scheduled_time,
                inspector["id"],
                inspector["name"],
            ),
        ).fetchone()
        if inspector_conflict is not None:
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.id,
                item.organization,
                item.location,
                item.date,
                item.time,
                item.inspector,
                item.status,
                item.site_latitude,
                item.site_longitude,
                item.site_radius_m,
                item.purpose,
                item.scope,
                item.inspector_id,
                item.inspection_request_id,
                item.notification_status,
            ),
        )
        if payload.notify_organization:
            connection.execute(
                """INSERT INTO inspection_notification_outbox
                (schedule_id, status) VALUES (?, 'pending')""",
                (item.id,),
            )

    if payload.notify_organization:
        notification_state = notification_service.deliver_schedule_notification(item.id)
        item = item.model_copy(update=notification_state)
    return item


def generate_random_schedule(count: int = 3) -> list[ScheduleItem]:
    """
    Persist unique upcoming demo assignments with randomized dates, times,
    organizations, and inspectors. Generated assignments always start as scheduled.
    """
    new_items: list[ScheduleItem] = []
    chooser = random.SystemRandom()
    first_date = date.today() + timedelta(days=1)

    with get_connection() as connection:
        organizations = connection.execute(
            """SELECT name, location, latitude, longitude, radius_m
            FROM organizations WHERE latitude IS NOT NULL AND longitude IS NOT NULL
            AND radius_m IS NOT NULL ORDER BY name"""
        ).fetchall()
        if not organizations:
            organizations = [
                {
                    "name": name,
                    "location": location,
                    "latitude": DEMO_SITE_COORDINATES[name]["latitude"],
                    "longitude": DEMO_SITE_COORDINATES[name]["longitude"],
                    "radius_m": DEMO_SITE_COORDINATES[name]["radius_m"],
                }
                for name, location in _DEMO_ORGANIZATIONS
            ]
        inspector_rows = connection.execute(
            """SELECT id, name, official_id, official_id_verified FROM users
            WHERE active = TRUE AND official_id IS NOT NULL AND trim(official_id) != ''
            ORDER BY id"""
        ).fetchall()
        if os.getenv("APP_ENV", "development").strip().lower() == "production":
            inspector_rows = [
                row for row in inspector_rows
                if row["official_id_verified"]
                and not row["official_id"].startswith(("DEMO-", "STAGING-"))
            ]
        active_inspectors = [
            (row["id"], row["name"]) for row in inspector_rows
        ]
        if not active_inspectors:
            raise LookupError("No active inspectors with verified official IDs are available.")
        candidates = [
            (organization, (first_date + timedelta(days=offset)).isoformat(), time)
            for offset in range(30)
            for organization in organizations
            for time in _DEMO_TIMES
        ]
        existing_rows = connection.execute(
            "SELECT organization, date, time, inspector, inspector_id FROM schedules"
        ).fetchall()
        occupied_slots = {
            (row["organization"], row["date"], row["time"])
            for row in existing_rows
        }
        busy_inspector_slots = {
            (row["date"], row["time"], row["inspector_id"])
            for row in existing_rows
            if row["inspector_id"] is not None
        }
        busy_legacy_inspector_slots = {
            (row["date"], row["time"], row["inspector"])
            for row in existing_rows
            if row["inspector_id"] is None
        }

        for organization, scheduled_date, scheduled_time in chooser.sample(
            candidates, len(candidates)
        ):
            if (organization["name"], scheduled_date, scheduled_time) in occupied_slots:
                continue
            available_inspectors = [
                inspector
                for inspector in active_inspectors
                if (scheduled_date, scheduled_time, inspector[0]) not in busy_inspector_slots
                and (scheduled_date, scheduled_time, inspector[1])
                not in busy_legacy_inspector_slots
            ]
            if not available_inspectors:
                continue

            inspector_id, inspector = chooser.choice(available_inspectors)
            new_items.append(
                ScheduleItem(
                    id=f"SCH-{uuid.uuid4().hex[:8].upper()}",
                    organization=organization["name"],
                    location=organization["location"],
                    date=scheduled_date,
                    time=scheduled_time,
                    inspector=inspector,
                    status="Scheduled",
                    site_latitude=organization["latitude"],
                    site_longitude=organization["longitude"],
                    site_radius_m=organization["radius_m"],
                    purpose="Routine compliance inspection",
                    scope="Review of registered records and organizational facilities.",
                    inspector_id=inspector_id,
                )
            )
            occupied_slots.add((organization["name"], scheduled_date, scheduled_time))
            busy_inspector_slots.add((scheduled_date, scheduled_time, inspector_id))
            if len(new_items) == count:
                break

        connection.executemany(
            """INSERT INTO schedules
            (id, organization, location, date, time, inspector, status,
            site_latitude, site_longitude, site_radius_m, purpose, scope, inspector_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    item.id, item.organization, item.location, item.date,
                    item.time, item.inspector, item.status, item.site_latitude,
                    item.site_longitude, item.site_radius_m, item.purpose,
                    item.scope, item.inspector_id,
                )
                for item in new_items
            ],
        )

    return new_items
