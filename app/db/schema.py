"""DDL: table creation and idempotent column migrations."""

DDL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    designation TEXT NOT NULL,
    region TEXT NOT NULL,
    specialization TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    experience_years INTEGER,
    bio TEXT NOT NULL DEFAULT '',
    username TEXT,
    temp_password TEXT,
    official_id TEXT,
    official_id_verified BOOLEAN NOT NULL DEFAULT FALSE,
    department_unit TEXT NOT NULL DEFAULT 'Inspection Department',
    jurisdiction TEXT,
    qualifications TEXT NOT NULL DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT
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
    contact TEXT NOT NULL DEFAULT '',
    requester_name TEXT NOT NULL DEFAULT '',
    requester_email TEXT NOT NULL DEFAULT '',
    requester_verified BOOLEAN NOT NULL DEFAULT FALSE,
    organization_id TEXT REFERENCES organizations(id),
    organization_display TEXT,
    purpose TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    urgency TEXT NOT NULL DEFAULT 'Routine',
    proposed_scope TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'Routine',
    status TEXT NOT NULL DEFAULT 'Pending',
    created_at TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT,
    new_organization TEXT
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

MIGRATIONS = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS official_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS official_id_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS department_unit TEXT NOT NULL DEFAULT 'Inspection Department';
ALTER TABLE users ADD COLUMN IF NOT EXISTS jurisdiction TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS qualifications TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS specialization TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS experience_years INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS temp_password TEXT;
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
ALTER TABLE inspection_requests ADD COLUMN IF NOT EXISTS organization_display TEXT;
ALTER TABLE inspection_requests ADD COLUMN IF NOT EXISTS new_organization TEXT;
ALTER TABLE inspection_requests ADD COLUMN IF NOT EXISTS contact TEXT NOT NULL DEFAULT '';
ALTER TABLE inspection_requests ADD COLUMN IF NOT EXISTS proposed_scope TEXT NOT NULL DEFAULT '';
ALTER TABLE inspection_requests ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'Routine';
ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT;
UPDATE users
SET jurisdiction = COALESCE(jurisdiction, region)
WHERE jurisdiction IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_official_id ON users(official_id);
"""
