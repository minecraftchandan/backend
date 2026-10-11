"""Demo-only random schedule generation for the Inspector Portal."""

import os
import random
import uuid
from datetime import date, timedelta

from app.database import DEMO_SITE_COORDINATES, get_connection
from app.schemas.schedule import ScheduleItem

_DEMO_ORGANIZATIONS = [
    ("Asha Bal Vikas Sanstha", "Kothrud, Pune"),
    ("Sanjeevani Old Age Support Trust", "Hadapsar, Pune"),
    ("Prerna Mahila Sangh", "Shivaji Nagar, Pune"),
    ("Gramin Shiksha Kendra", "Wagholi, Pune"),
    ("Nirmal Jeevan Foundation", "Kondhwa, Pune"),
    ("Disha Punarvasan Kendra", "Aundh, Pune"),
]

_DEMO_TIMES = ["09:30 AM", "10:30 AM", "11:00 AM", "02:00 PM", "03:30 PM"]


def generate_random_schedule(count: int = 3) -> list[ScheduleItem]:
    """
    Persist unique upcoming demo assignments with randomized dates, times,
    organizations, and inspectors. Generated assignments always start as Scheduled.
    """
    new_items: list[ScheduleItem] = []
    chooser = random.SystemRandom()
    first_date = date.today() + timedelta(days=1)
    is_production = os.getenv("APP_ENV", "development").strip().lower() == "production"

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
        if is_production:
            inspector_rows = [
                row for row in inspector_rows
                if row["official_id_verified"]
                and not row["official_id"].startswith(("DEMO-", "STAGING-"))
            ]
        active_inspectors = [(row["id"], row["name"]) for row in inspector_rows]
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
        occupied_slots = {(r["organization"], r["date"], r["time"]) for r in existing_rows}
        busy_id_slots = {(r["date"], r["time"], r["inspector_id"]) for r in existing_rows if r["inspector_id"]}
        busy_name_slots = {(r["date"], r["time"], r["inspector"]) for r in existing_rows if not r["inspector_id"]}

        for organization, scheduled_date, scheduled_time in chooser.sample(candidates, len(candidates)):
            if (organization["name"], scheduled_date, scheduled_time) in occupied_slots:
                continue
            available = [
                i for i in active_inspectors
                if (scheduled_date, scheduled_time, i[0]) not in busy_id_slots
                and (scheduled_date, scheduled_time, i[1]) not in busy_name_slots
            ]
            if not available:
                continue

            inspector_id, inspector_name = chooser.choice(available)
            new_items.append(ScheduleItem(
                id=f"SCH-{uuid.uuid4().hex[:8].upper()}",
                organization=organization["name"],
                location=organization["location"],
                date=scheduled_date,
                time=scheduled_time,
                inspector=inspector_name,
                status="Scheduled",
                site_latitude=organization["latitude"],
                site_longitude=organization["longitude"],
                site_radius_m=organization["radius_m"],
                purpose="Routine compliance inspection",
                scope="Review of registered records and organizational facilities.",
                inspector_id=inspector_id,
            ))
            occupied_slots.add((organization["name"], scheduled_date, scheduled_time))
            busy_id_slots.add((scheduled_date, scheduled_time, inspector_id))
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
