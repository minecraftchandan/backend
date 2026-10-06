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

_DEMO_ORGANIZATIONS = [
    ("Asha Bal Vikas Sanstha", "Kothrud, Pune"),
    ("Sanjeevani Old Age Support Trust", "Hadapsar, Pune"),
    ("Prerna Mahila Sangh", "Shivaji Nagar, Pune"),
    ("Gramin Shiksha Kendra", "Wagholi, Pune"),
    ("Nirmal Jeevan Foundation", "Kondhwa, Pune"),
    ("Disha Punarvasan Kendra", "Aundh, Pune"),
]

_DEMO_INSPECTORS = ["Ramesh Kadam", "Sunita Patil", "Arjun Deshmukh"]

_DEMO_TIMES = ["09:30 AM", "10:30 AM", "11:00 AM", "02:00 PM", "03:30 PM"]

def get_all_schedules() -> list[ScheduleItem]:
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT id, organization, location, date, time, inspector, status,
            site_latitude, site_longitude, site_radius_m FROM schedules ORDER BY date, time"""
        ).fetchall()
    return [_with_site_location(ScheduleItem.model_validate(dict(row))) for row in rows]


def get_schedule_by_id(schedule_id: str) -> ScheduleItem | None:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT id, organization, location, date, time, inspector, status,
            site_latitude, site_longitude, site_radius_m FROM schedules WHERE id = ?""",
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
            "SELECT name FROM users WHERE id = ?",
            (payload.inspector_id,),
        ).fetchone()
        if inspector is None:
            raise LookupError("The selected inspector could not be found.")

        inspector_conflict = connection.execute(
            """SELECT id FROM schedules
            WHERE date = ? AND time = ? AND inspector = ?
            AND lower(status) != 'completed' LIMIT 1""",
            (payload.date.isoformat(), scheduled_time, inspector["name"]),
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
        )
        connection.execute(
            """INSERT INTO schedules
            (id, organization, location, date, time, inspector, status,
            site_latitude, site_longitude, site_radius_m)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            ),
        )

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
        candidates = [
            (organization, (first_date + timedelta(days=offset)).isoformat(), time)
            for offset in range(30)
            for organization in organizations
            for time in _DEMO_TIMES
        ]
        existing_rows = connection.execute(
            "SELECT organization, date, time, inspector FROM schedules"
        ).fetchall()
        occupied_slots = {
            (row["organization"], row["date"], row["time"])
            for row in existing_rows
        }
        busy_inspector_slots = {
            (row["date"], row["time"], row["inspector"])
            for row in existing_rows
        }

        for organization, scheduled_date, scheduled_time in chooser.sample(
            candidates, len(candidates)
        ):
            if (organization["name"], scheduled_date, scheduled_time) in occupied_slots:
                continue
            available_inspectors = [
                inspector
                for inspector in _DEMO_INSPECTORS
                if (scheduled_date, scheduled_time, inspector) not in busy_inspector_slots
            ]
            if not available_inspectors:
                continue

            inspector = chooser.choice(available_inspectors)
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
                )
            )
            occupied_slots.add((organization["name"], scheduled_date, scheduled_time))
            busy_inspector_slots.add((scheduled_date, scheduled_time, inspector))
            if len(new_items) == count:
                break

        connection.executemany(
            """INSERT INTO schedules
            (id, organization, location, date, time, inspector, status,
            site_latitude, site_longitude, site_radius_m)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    item.id, item.organization, item.location, item.date,
                    item.time, item.inspector, item.status, item.site_latitude,
                    item.site_longitude, item.site_radius_m,
                )
                for item in new_items
            ],
        )

    return new_items
