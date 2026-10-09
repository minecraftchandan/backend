"""PostgreSQL persistence for the deployable demo backend."""

import os
import json
import hashlib
import re
import secrets
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from app.portal_demo_seed import DEMO_ACCOUNTS, PORTAL_DEMO_DATA

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_initialization_lock = Lock()
_initialized = False


class PostgresConnection:
    """Small adapter for the existing parameterized SQL used by the demo services."""

    def __init__(self, connection: psycopg.Connection):
        self._connection = connection

    @staticmethod
    def _translate(query: str) -> str:
        translated = re.sub(
            r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
            "INSERT INTO",
            query,
            flags=re.IGNORECASE,
        )
        ignored_conflicts = translated != query
        translated = translated.replace("?", "%s")
        translated = re.sub(r"(?<!:):([A-Za-z_]\w*)", r"%(\1)s", translated)
        if ignored_conflicts:
            translated = translated.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return translated

    def execute(self, query: str, params: Any = None):
        return self._connection.execute(self._translate(query), params)

    def executemany(self, query: str, params_seq):
        cursor = self._connection.cursor()
        cursor.executemany(self._translate(query), params_seq)
        return cursor

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

_DEMO_USERS = (
    (1, "Ramesh Kadam", "Field Inspector", "Pune Division", "DEMO-INS-0001", "Inspection Department", "Pune Division", True),
    (2, "Sunita Patil", "Field Inspector", "Nashik Division", "DEMO-INS-0002", "Inspection Department", "Nashik Division", True),
    (3, "Arjun Deshmukh", "Senior Inspector", "Pune Division", "DEMO-INS-0003", "Inspection Department", "Pune Division", True),
)

_STAGING_TEST_INSPECTOR = (
    999999,
    "Staging Finance QA Inspector",
    "Finance Compliance QA Inspector",
    "Sandbox District",
    "STAGING-TEST-NOT-OFFICIAL",
    False,
    "Staging QA Unit",
    "Sandbox District",
    "Synthetic finance and accounting review qualification; not a real credential.",
    True,
)

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

def _seed_demo_inspection_history(connection: PostgresConnection) -> None:
    india_timezone = timezone(timedelta(hours=5, minutes=30))
    organizations = connection.execute(
        """SELECT name, location, latitude, longitude
        FROM organizations ORDER BY name"""
    ).fetchall()
    inspectors = [item[0] for item in _DEMO_USERS]
    deleted_ids = {
        row["id"] for row in connection.execute("SELECT id FROM deleted_inspections")
    }
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
        rows.append(
            (
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
            )
        )
    connection.executemany(
        """INSERT OR IGNORE INTO inspections (
            id, organization, location, date, time, inspector, status, notes,
            latitude, longitude, location_accuracy_m, location_captured_at,
            photo_captured_at, location_distance_m, location_verified,
            location_check_status, photo_media_id, submitted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


def _initialize_connection(connection: PostgresConnection) -> None:
    global _initialized
    if _initialized:
        return

    with _initialization_lock:
        if _initialized:
            return

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                designation TEXT NOT NULL,
                region TEXT NOT NULL,
                official_id TEXT,
                official_id_verified BOOLEAN NOT NULL DEFAULT FALSE,
                department_unit TEXT NOT NULL DEFAULT 'Inspection Department',
                jurisdiction TEXT,
                qualifications TEXT NOT NULL DEFAULT '',
                active BOOLEAN NOT NULL DEFAULT TRUE
            );
            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                organization TEXT NOT NULL,
                location TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                inspector TEXT NOT NULL,
                status TEXT NOT NULL,
                site_latitude REAL,
                site_longitude REAL,
                site_radius_m REAL,
                purpose TEXT,
                scope TEXT,
                inspector_id INTEGER,
                inspection_request_id TEXT,
                organization_notified BOOLEAN NOT NULL DEFAULT FALSE,
                notification_status TEXT NOT NULL DEFAULT 'not_requested',
                notification_error TEXT
            );
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                reg TEXT NOT NULL UNIQUE,
                location TEXT NOT NULL,
                address TEXT NOT NULL,
                verification TEXT NOT NULL DEFAULT 'Pending',
                risk TEXT NOT NULL DEFAULT 'Review',
                latitude REAL,
                longitude REAL,
                radius_m REAL,
                contact_email TEXT,
                contact_person TEXT,
                contact_email_verified BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS inspection_requests (
                id TEXT PRIMARY KEY,
                department TEXT NOT NULL,
                requester_name TEXT NOT NULL,
                requester_email TEXT NOT NULL,
                requester_verified BOOLEAN NOT NULL DEFAULT FALSE,
                organization_id TEXT NOT NULL REFERENCES organizations(id),
                purpose TEXT NOT NULL,
                scope TEXT NOT NULL,
                urgency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT NOT NULL,
                reviewed_by TEXT,
                reviewed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_inspection_requests_status_created
                ON inspection_requests(status, created_at);
            CREATE TABLE IF NOT EXISTS inspection_notification_outbox (
                schedule_id TEXT PRIMARY KEY REFERENCES schedules(id),
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                recipient_email TEXT,
                last_error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                delivered_at TIMESTAMPTZ
            );
            CREATE TABLE IF NOT EXISTS inspection_request_rate_limits (
                bucket_key TEXT NOT NULL,
                window_start TIMESTAMPTZ NOT NULL,
                request_count INTEGER NOT NULL,
                PRIMARY KEY (bucket_key, window_start)
            );
            CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules(date);
            CREATE TABLE IF NOT EXISTS inspections (
                id TEXT PRIMARY KEY,
                organization TEXT NOT NULL,
                location TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                inspector TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT,
                schedule_id TEXT,
                scheduled_date TEXT,
                scheduled_time TEXT,
                latitude REAL,
                longitude REAL,
                location_accuracy_m REAL,
                location_captured_at TEXT,
                photo_captured_at TEXT,
                submitted_at TEXT,
                client_submission_id TEXT UNIQUE,
                location_distance_m REAL,
                location_verified INTEGER,
                location_check_status TEXT,
                photo_media_id TEXT
            );
            CREATE TABLE IF NOT EXISTS deleted_inspections (
                id TEXT PRIMARY KEY,
                deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_inspections_date ON inspections(date);
            CREATE TABLE IF NOT EXISTS portal_data (
                data_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS portal_settings (
                setting_id INTEGER PRIMARY KEY CHECK (setting_id = 1),
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accounts (
                username TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                display_name TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence_media (
                media_id TEXT PRIMARY KEY,
                media_type TEXT NOT NULL,
                content BYTEA NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reverse_geocode_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                cached_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        connection.executescript(
            """
            ALTER TABLE users ADD COLUMN IF NOT EXISTS official_id TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS official_id_verified BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS department_unit TEXT NOT NULL DEFAULT 'Inspection Department';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS jurisdiction TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS qualifications TEXT NOT NULL DEFAULT '';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
            ALTER TABLE schedules ADD COLUMN IF NOT EXISTS purpose TEXT;
            ALTER TABLE schedules ADD COLUMN IF NOT EXISTS scope TEXT;
            ALTER TABLE schedules ADD COLUMN IF NOT EXISTS inspector_id INTEGER;
            ALTER TABLE schedules ADD COLUMN IF NOT EXISTS inspection_request_id TEXT;
            ALTER TABLE schedules ADD COLUMN IF NOT EXISTS organization_notified BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE schedules ADD COLUMN IF NOT EXISTS notification_status TEXT NOT NULL DEFAULT 'not_requested';
            ALTER TABLE schedules ADD COLUMN IF NOT EXISTS notification_error TEXT;
            ALTER TABLE organizations ADD COLUMN IF NOT EXISTS contact_email TEXT;
            ALTER TABLE organizations ADD COLUMN IF NOT EXISTS contact_person TEXT;
            ALTER TABLE organizations ADD COLUMN IF NOT EXISTS contact_email_verified BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE inspection_requests ADD COLUMN IF NOT EXISTS requester_verified BOOLEAN NOT NULL DEFAULT FALSE;
            UPDATE users
            SET jurisdiction = COALESCE(jurisdiction, region)
            WHERE jurisdiction IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_official_id ON users(official_id);
            """
        )
        connection.executemany(
            """INSERT OR IGNORE INTO users
            (id, name, designation, region, official_id, department_unit, jurisdiction, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            _DEMO_USERS,
        )
        if os.getenv("APP_ENV", "development").strip().lower() == "staging":
            connection.execute(
                """INSERT INTO users
                (id, name, designation, region, official_id, official_id_verified,
                 department_unit, jurisdiction, qualifications, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO NOTHING""",
                _STAGING_TEST_INSPECTOR,
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
            [
                (item[7], item[8], item[9], item[0])
                for item in _DEMO_SCHEDULES
            ],
        )
        connection.executemany(
            """UPDATE schedules SET location = ?, date = ?, time = ?, inspector = ?
            WHERE id = ? AND status = 'Scheduled' AND date < ?""",
            [
                (item[2], item[3], item[4], item[5], item[0], date.today().isoformat())
                for item in _DEMO_SCHEDULES
            ],
        )
        deleted_inspection_ids = {
            row["id"] for row in connection.execute("SELECT id FROM deleted_inspections")
        }
        connection.executemany(
            """INSERT OR IGNORE INTO inspections (
                id, organization, location, date, time, inspector, status, notes,
                schedule_id, latitude, longitude, location_accuracy_m,
                location_captured_at, client_submission_id, location_distance_m,
                location_verified, location_check_status, photo_media_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [item for item in _DEMO_INSPECTIONS if item[0] not in deleted_inspection_ids],
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
                if item[0] not in deleted_inspection_ids
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
            existing_account = connection.execute(
                "SELECT username FROM accounts WHERE username = ?",
                (username,),
            ).fetchone()
            if existing_account is None:
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
        demo_photo = Path(__file__).resolve().parents[1] / "src" / "assets" / "inspection-evidence.jpg"
        if demo_photo.is_file():
            connection.execute(
                "INSERT OR IGNORE INTO evidence_media (media_id, media_type, content) VALUES (?, ?, ?)",
                ("demo-inspection-photo", "image/jpeg", demo_photo.read_bytes()),
            )
        connection.commit()
        _initialized = True


@contextmanager
def get_connection() -> Iterator[PostgresConnection]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be set to a PostgreSQL connection URL.")
    connection = PostgresConnection(
        psycopg.connect(DATABASE_URL, connect_timeout=10, row_factory=dict_row)
    )
    try:
        _initialize_connection(connection)
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with get_connection():
        pass