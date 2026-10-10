"""Demo seed data constants and seeding logic."""

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.portal_demo_seed import DEMO_ACCOUNTS, PORTAL_DEMO_DATA

DEMO_SITE_COORDINATES = {
    "Asha Bal Vikas Sanstha": {"latitude": 18.5074, "longitude": 73.8077, "radius_m": 100},
    "Sanjeevani Old Age Support Trust": {"latitude": 18.5020, "longitude": 73.9270, "radius_m": 100},
    "Prerna Mahila Sangh": {"latitude": 18.5308, "longitude": 73.8475, "radius_m": 100},
    "Gramin Shiksha Kendra": {"latitude": 18.5793, "longitude": 73.9780, "radius_m": 100},
    "Nirmal Jeevan Foundation": {"latitude": 18.4672, "longitude": 73.8900, "radius_m": 100},
    "Disha Punarvasan Kendra": {"latitude": 18.5580, "longitude": 73.8070, "radius_m": 100},
}

_PORTAL_DEMO_COORDINATES = {
    "Seva Foundation": (28.6139, 77.2090),
    "Udaan Welfare Society": (28.5355, 77.3910),
    "Jan Kalyan Trust": (28.7041, 77.1025),
    "Shakti Rural Development Centre": (28.4595, 77.0266),
    "Hope Community Foundation": (28.4089, 77.3178),
}

_DEMO_SITE_LOCATIONS = {
    "Asha Bal Vikas Sanstha": "Kothrud, Pune",
    "Sanjeevani Old Age Support Trust": "Hadapsar, Pune",
    "Prerna Mahila Sangh": "Shivaji Nagar, Pune",
    "Gramin Shiksha Kendra": "Wagholi, Pune",
    "Nirmal Jeevan Foundation": "Kondhwa, Pune",
    "Disha Punarvasan Kendra": "Aundh, Pune",
}

_DEMO_USERS = (
    (1, "Ramesh Kadam", "Field Inspector", "Pune Division", "DEMO-INS-0001", "Inspection Department", "Pune Division", True),
    (2, "Sunita Patil", "Field Inspector", "Nashik Division", "DEMO-INS-0002", "Inspection Department", "Nashik Division", True),
    (3, "Arjun Deshmukh", "Senior Inspector", "Pune Division", "DEMO-INS-0003", "Inspection Department", "Pune Division", True),
)

_today = date.today()
_DEMO_SCHEDULES = (
    ("SCH-1001", "Asha Bal Vikas Sanstha", "Kothrud, Pune", (_today + timedelta(days=2)).isoformat(), "10:30 AM", "Ramesh Kadam", "Scheduled", 18.5074, 73.8077, 100),
    ("SCH-1002", "Sanjeevani Old Age Support Trust", "Hadapsar, Pune", (_today + timedelta(days=4)).isoformat(), "02:00 PM", "Ramesh Kadam", "Scheduled", 18.5020, 73.9270, 100),
)

_DEMO_INSPECTIONS = (
    ("REC-1001", "Nirmal Jeevan Foundation", "Kondhwa, Pune", "2026-09-18", "10:00 AM", "Ramesh Kadam", "Verified", "Records and facilities found in order.", None, 18.4672, 73.8900, 8, "2026-09-18T10:00:00+05:30", None, 0, 1, "verified", "demo-inspection-photo"),
    ("REC-1002", "Asha Bal Vikas Sanstha", "Kothrud, Pune", "2026-09-20", "11:15 AM", "Sunita Patil", "Verified", "Demo visit inside the registered boundary.", "SCH-1001", 18.5075, 73.8078, 12, "2026-09-20T11:15:00+05:30", None, 14, 1, "verified", "demo-inspection-photo"),
    ("REC-1003", "Sanjeevani Old Age Support Trust", "Hadapsar, Pune", "2026-09-22", "02:20 PM", "Arjun Deshmukh", "Flagged", "Demo visit outside the configured boundary.", "SCH-1002", 18.5045, 73.9300, 10, "2026-09-22T14:20:00+05:30", None, 320, 0, "outside_radius", "demo-inspection-photo"),
    ("REC-1004", "Prerna Mahila Sangh", "Shivaji Nagar, Pune", "2026-09-25", "09:40 AM", "Ramesh Kadam", "Submitted", "Demo record awaiting authority review.", None, 18.5308, 73.8475, 18, "2026-09-25T09:40:00+05:30", None, None, None, "not_configured", "demo-inspection-photo"),
    ("REC-1005", "Gramin Shiksha Kendra", "Wagholi, Pune", "2026-09-28", "03:10 PM", "Sunita Patil", "Verified", "Demo visit inside the registered boundary.", None, 18.5793, 73.9780, 9, "2026-09-28T15:10:00+05:30", None, 0, 1, "verified", "demo-inspection-photo"),
)


def _seed_demo_inspection_history(connection) -> None:
    india_timezone = timezone(timedelta(hours=5, minutes=30))
    organizations = connection.execute(
        "SELECT name, location, latitude, longitude FROM organizations ORDER BY name"
    ).fetchall()
    inspectors = [item[0] for item in _DEMO_USERS]
    deleted_ids = {row["id"] for row in connection.execute("SELECT id FROM deleted_inspections")}
    rows = []
    for index in range(30):
        inspection_id = f"DEMO-HIST-{index + 1:03d}"
        if inspection_id in deleted_ids:
            continue
        organization = organizations[(index * 7) % len(organizations)]
        captured_at = datetime.now(india_timezone).replace(second=0, microsecond=0) - timedelta(
            days=((index * 11) % 30) + 1,
            hours=index % 8,
        )
        status = ("Verified", "Verified", "Submitted", "Flagged", "Verified")[index % 5]
        latitude = organization["latitude"]
        longitude = organization["longitude"]
        distance_m = 12.0
        location_verified = 1
        location_check_status = "verified"
        if status == "Flagged" and latitude is not None:
            latitude += 0.004
            distance_m = 445.0
            location_verified = 0
            location_check_status = "outside_radius"
        rows.append((
            inspection_id,
            organization["name"],
            organization["location"],
            captured_at.date().isoformat(),
            captured_at.strftime("%I:%M %p"),
            inspectors[index % len(inspectors)],
            status,
            "Fictional historical demo inspection.",
            latitude,
            longitude,
            10.0,
            captured_at.isoformat(),
            captured_at.isoformat(),
            distance_m,
            location_verified,
            location_check_status,
            "demo-inspection-photo",
            captured_at.astimezone(timezone.utc).isoformat(),
        ))
    connection.executemany(
        """INSERT OR IGNORE INTO inspections (
            id, organization, location, date, time, inspector, status, notes,
            latitude, longitude, location_accuracy_m, location_captured_at,
            photo_captured_at, location_distance_m, location_verified,
            location_check_status, photo_media_id, submitted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


def apply_seed(connection) -> None:
    """Insert all demo data. Called once during database initialization."""
    connection.executemany(
        """INSERT OR IGNORE INTO users
        (id, name, designation, region, official_id, department_unit, jurisdiction, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        _DEMO_USERS,
    )

    seeded_organizations = [
        (
            item["id"], item["name"], item["reg"], item["location"],
            item["address"], item["verification"], item["risk"],
            *_PORTAL_DEMO_COORDINATES.get(item["name"], (None, None)),
            100 if item["name"] in _PORTAL_DEMO_COORDINATES else None,
        )
        for item in PORTAL_DEMO_DATA["organizations"]
    ]
    portal_names = {item["name"] for item in PORTAL_DEMO_DATA["organizations"]}
    seeded_organizations.extend(
        (
            f"demo-site-{index:02d}", name, f"DEMO-PUNE-{index:02d}", location,
            location, "Verified", "Review", site["latitude"], site["longitude"], site["radius_m"],
        )
        for index, (name, site) in enumerate(DEMO_SITE_COORDINATES.items(), start=1)
        if name not in portal_names
        for location in (_DEMO_SITE_LOCATIONS[name],)
    )
    connection.executemany(
        """INSERT OR IGNORE INTO organizations
        (id, name, reg, location, address, verification, risk, latitude, longitude, radius_m)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        seeded_organizations,
    )

    connection.executemany(
        """INSERT OR IGNORE INTO schedules
        (id, organization, location, date, time, inspector, status,
        site_latitude, site_longitude, site_radius_m)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        _DEMO_SCHEDULES,
    )
    connection.execute(
        """UPDATE schedules
        SET inspector_id = (
            SELECT id FROM users
            WHERE users.name = schedules.inspector ORDER BY id LIMIT 1
        )
        WHERE inspector_id IS NULL AND EXISTS (
            SELECT 1 FROM users WHERE users.name = schedules.inspector
        )"""
    )
    connection.executemany(
        """UPDATE schedules SET site_latitude = ?, site_longitude = ?, site_radius_m = ?
        WHERE id = ? AND site_latitude IS NULL""",
        [(item[7], item[8], item[9], item[0]) for item in _DEMO_SCHEDULES],
    )
    connection.executemany(
        """UPDATE schedules SET location = ?, date = ?, time = ?, inspector = ?
        WHERE id = ? AND status = 'Scheduled' AND date < ?""",
        [
            (item[2], item[3], item[4], item[5], item[0], date.today().isoformat())
            for item in _DEMO_SCHEDULES
        ],
    )

    deleted_ids = {row["id"] for row in connection.execute("SELECT id FROM deleted_inspections")}
    connection.executemany(
        """INSERT OR IGNORE INTO inspections (
            id, organization, location, date, time, inspector, status, notes,
            schedule_id, latitude, longitude, location_accuracy_m,
            location_captured_at, client_submission_id, location_distance_m,
            location_verified, location_check_status, photo_media_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [item for item in _DEMO_INSPECTIONS if item[0] not in deleted_ids],
    )
    connection.executemany(
        """UPDATE inspections SET
            latitude = COALESCE(latitude, ?),
            longitude = COALESCE(longitude, ?),
            location_accuracy_m = COALESCE(location_accuracy_m, ?),
            location_captured_at = COALESCE(location_captured_at, ?),
            location_distance_m = COALESCE(location_distance_m, ?),
            location_verified = COALESCE(location_verified, ?),
            location_check_status = CASE
                WHEN location_check_status IS NULL OR location_check_status = 'not_configured'
                THEN ? ELSE location_check_status END,
            photo_media_id = COALESCE(photo_media_id, ?)
        WHERE id = ? AND client_submission_id IS NULL""",
        [
            (item[9], item[10], item[11], item[12], item[14], item[15], item[16], item[17], item[0])
            for item in _DEMO_INSPECTIONS
            if item[0] not in deleted_ids
        ],
    )
    _seed_demo_inspection_history(connection)

    connection.execute(
        """UPDATE schedules SET status = 'Completed'
        WHERE id IN (
            SELECT schedule_id FROM inspections
            WHERE client_submission_id IS NOT NULL AND schedule_id IS NOT NULL
        ) AND status = 'Scheduled'"""
    )

    connection.execute(
        "INSERT OR IGNORE INTO portal_data (data_key, payload) VALUES (?, ?)",
        ("demo", json.dumps(PORTAL_DEMO_DATA)),
    )
    connection.execute(
        "INSERT OR IGNORE INTO portal_settings (setting_id, payload) VALUES (?, ?)",
        (1, json.dumps(PORTAL_DEMO_DATA["settings"])),
    )

    for username, role, display_name, password in DEMO_ACCOUNTS:
        existing = connection.execute(
            "SELECT username FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if existing is None:
            salt = secrets.token_bytes(16)
            password_hash = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, 310_000
            ).hex()
            connection.execute(
                """INSERT INTO accounts
                (username, role, display_name, password_salt, password_hash)
                VALUES (?, ?, ?, ?, ?)""",
                (username, role, display_name, salt.hex(), password_hash),
            )

    demo_photo = Path(__file__).resolve().parents[2] / "src" / "assets" / "inspection-evidence.jpg"
    if demo_photo.is_file():
        connection.execute(
            "INSERT OR IGNORE INTO evidence_media (media_id, media_type, content) VALUES (?, ?, ?)",
            ("demo-inspection-photo", "image/jpeg", demo_photo.read_bytes()),
        )
