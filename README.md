# Satark Drishti API + PostgreSQL (Render)

This is a self-contained deployment copy of the FastAPI backend. It connects to
any hosted PostgreSQL provider (such as Neon) through `DATABASE_URL`, initializes
the schema and fictional demo records on startup, and stores uploaded inspection
evidence in PostgreSQL `BYTEA` columns. The original `backend/` folder remains
unchanged and continues to use SQLite for local development.

## Create a hosted PostgreSQL database

1. Create a PostgreSQL project with Neon (or another hosted PostgreSQL provider).
2. Copy its connection string. For Neon, use the pooled connection string for a
   web service and retain the provider's SSL parameters.
3. Keep the connection string private; it contains database credentials.

## Deploy the API to Render

1. Push this repository to GitHub and create the Neon database as described above.
2. In Render, choose **New > Blueprint** and connect the new repository
   containing these files at its root.
3. Select `render.yaml` as the Blueprint file. It provisions only the Python
   API web service; the API sources, dependencies, and Blueprint are all at
   the repository root.
4. When prompted for environment values, set:
   - `DATABASE_URL`: the PostgreSQL connection string copied from Neon.
   - `TRUSTED_HOSTS`: the API's exact Render hostname, such as
     `satark-drishti-api.onrender.com` (without `https://`).
   - `ALLOWED_ORIGINS`: the exact origin of the deployed frontend, including
     `https://` and no trailing slash, for example `https://example.onrender.com`.
     If multiple frontends call the API, comma-separate their origins.
5. Wait for the service health check at `/api/health` to pass. The API's
   generated `API_ACCESS_TOKEN` is in the service's Environment settings. Keep
   it secret. The local Vite development proxy uses it server-side. The mobile
   app signs in through `/api/auth/login` and receives a short-lived,
   user-specific bearer token signed with this secret; the shared secret itself
   is never sent to or embedded in the app. Add `https://localhost` to
   `ALLOWED_ORIGINS` for the Capacitor Android WebView, in addition to any
   browser frontend origins.

Render uses the repository root and `requirements.txt` to install dependencies,
then starts Uvicorn on Render's assigned `$PORT`.

## Local PostgreSQL run

Create a PostgreSQL database, copy `.env.example` to `.env`, and set
`DATABASE_URL` to its connection URL. Install and run from this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The database schema is created on the first startup. Local demo accounts and
fictional sample data are seeded automatically. The first registered records
and inspection evidence uploaded after deployment are persisted in PostgreSQL.

## Import the local SQLite snapshot

The repository includes a generator that reads `backend/data/satark.sqlite3`
and writes `backend&db/local-import.sql`:

```powershell
python backend&db/scripts/export_sqlite_to_postgres.py
```

Run the importer from the repository root. It prompts for the Neon connection
URL with hidden input, creates/initializes the backend tables and demo seed in
Neon, then imports the SQLite snapshot:

```powershell
python "backend&db/scripts/import_sqlite_export_to_postgres.py"
```

It validates the generated file and imports transactionally. The SQL uses
upserts for matching primary keys and removes inspections recorded as deleted
in the SQLite tombstone table. You do not need to deploy the Render API first.
Run it only against the intended project database; it imports personal/project
records over matching seeded rows.

The SQL dump is ignored by Git because it contains account password hashes and
embedded evidence images. Do not publish or share it. Regenerate it after any
local SQLite changes that need to be included.

## Import the root MySQL SQL samples into PostgreSQL

The repository also has `Inspection_System1.sql`, `Sample_Input.sql`, and
`Sample_Output.sql` in its root. Those scripts are MySQL-flavored; `Sample_Output`
contains only SELECT statements, while `Sample_Input.sql` seeds one NGO, inspector,
inspection, and evidence record. Import that sample as PostgreSQL with:

```powershell
python backend&db/scripts/import_root_sql_to_postgres.py
```

The script asks for the PostgreSQL URL with hidden input, or reads
`ROOT_SQL_DATABASE_URL` if set. It creates the PostGIS-backed
`inspection_system` schema and imports the sample there idempotently. This is
separate from the FastAPI backend's public `public` schema. Do not enter a
connection URL into chat, commit it, or target a database unless you intend to
create this schema and sample data there.

## Important limitations and deployment notes

- Neon Free is suitable for demos and has usage/storage limits and scale-to-zero;
  check the provider's current plan limits before relying on it.
- Render Free web services spin down when idle.
- The existing local SQLite database is intentionally not copied or imported.
  Its organizations, schedules, inspection records, and uploaded images stay
  on the development machine. This deployment starts from the included demo
  seed; arrange a deliberate migration if local data must be retained.
- Store `DATABASE_URL` and `API_ACCESS_TOKEN` only in Render's environment
  settings. Do not commit `.env` files or place the shared token in frontend
  source or an APK. Rotating `API_ACCESS_TOKEN` invalidates issued app sessions.
- The Authority and Inspector clients use the per-user bearer token returned
  at login when calling protected API routes. It expires after 12 hours, after
  which the user signs in again. The legacy shared token remains accepted for
  the trusted local Vite proxy; it must not be exposed to public clients.
- CORS and trusted-host values must be restricted to the actual deployed
  domains. Do not use `*`.
- This API deployment does not host MediaMTX. Live RTMP/WebRTC monitoring needs
  a separate streaming host with the required TCP/UDP ports and network rules.

## Department inspection requests and scheduling

The API applies its schema migrations idempotently during application startup.
The request submission endpoint is intentionally public for the department
form; submissions are rate-limited to five requests per source in each
15-minute window. Department, requester name, and requester email are
unverified user-supplied claims. The submitted organization display name is
never used to associate a request: the API resolves the authoritative name
from `organization_id`. A request is only a request and never authorizes an
inspection or creates a schedule.

Government departments should be authenticated before their details are treated
as verified. Until a department identity-verification process is integrated,
Authority Officers must verify the submitting department and contact details
through an independent official channel before relying on them.

### Request endpoints

| Method and path | Access | Behavior |
| --- | --- | --- |
| `POST /api/inspection-requests` | Public; rate-limited | Accepts `department`, `requester_name`, `requester_email`, `organization_id`, `organization` (display-only), `purpose`, `scope`, and `urgency` (`Routine`, `Time-sensitive`, or `Urgent`). Returns the persisted request with a server ID, UTC `created_at`, `Pending` status, authoritative organization name, and `requester_verified: false`. |
| `GET /api/inspection-requests` | Signed Authority Officer session | Returns the review inbox. |
| `PATCH /api/inspection-requests/{id}` | Signed Authority Officer session | Accepts only `{"status":"Approved"}` or `{"status":"Rejected"}`. A request may transition once from `Pending`; closed requests return `409`. Review username and timestamp are persisted. Approval does not create a schedule. |

The submission body has the fields in the contract above. Each submission,
inbox item, and review response contains `id`, `department`, `requester_name`,
`requester_email`, `requester_verified`, `organization_id`, authoritative
`organization`, `purpose`, `scope`, `urgency`, `status`, and ISO-8601
`created_at`; reviewed items also contain `reviewed_by` and `reviewed_at`.

The private inbox and all schedule mutations require the per-user bearer token
issued by `/api/auth/login` for the **Authority Officer** role. The legacy
shared API token and Inspector sessions do not grant these permissions.

### Schedule endpoints and organization contact verification

`POST /api/schedule` requires an Authority Officer and accepts
`organization_id`, active `inspector_id`, future `date` (`YYYY-MM-DD`),
`time` (`HH:MM`), meaningful `purpose` and `scope`, optional
`inspection_request_id`, and `notify_organization` (defaults to `true`). When a
request ID is supplied, the request must be `Approved` and belong to the same
organization. Creating a schedule directly is still an officer-only action;
request approval itself never schedules one.

For example:

```json
{
  "organization_id": "registered-org-id",
  "inspector_id": 12,
  "date": "2030-02-03",
  "time": "10:30",
  "purpose": "Review reported compliance concerns",
  "scope": "Review records and inspect organizational facilities",
  "inspection_request_id": "IR-0123456789ABCDEF",
  "notify_organization": true
}
```

`GET /api/schedule` includes purpose and scope for inspectors to review, and
continues to return historical rows with null purpose/scope. The successful
schedule response includes `id`, authoritative `organization`,
`organization_notified`, `notification_status`, and, if applicable,
`notification_error`, plus schedule date/time, purpose/scope, assigned
inspector, and status. A notification is marked delivered only after SMTP
accepts it. `POST /api/schedule/{id}/notification/retry` retries a failed
notification and also requires an Authority Officer.

Inspector profiles are stored on the backend with `official_id`, name,
designation, department/unit, jurisdiction, and active status. An Authority
Officer manages a profile through
`PUT /api/users/{user_id}/profile` with `name`, `designation`, `official_id`,
`department_unit`, `jurisdiction`, and `active`. A schedule cannot be
assigned to an inactive inspector or one without an official ID. Legacy
profiles start with no official ID and must be verified and updated before
assignment. Seeded `DEMO-INS-*` IDs are demo placeholders, not government
identifiers; replace them with verified values before production scheduling.

Organizations have a verified contact email and contact person. An Authority
Officer can set/verify these fields using
`PATCH /api/organizations/{organization_id}/verified-contact` with
`{"contact_email":"...","contact_person":"..."}`. Verify ownership of the
address through an independent channel before using this endpoint. The contact
email is not exposed in organization list/detail responses, and department
requester emails are never used as organization destinations.

### SMTP configuration and delivery state

To enable organization notices, configure these environment variables on the
backend service:

| Variable | Required | Description |
| --- | --- | --- |
| `SMTP_HOST` | Yes | SMTP provider hostname. |
| `SMTP_PORT` | No | SMTP port; defaults to `587`. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Together, if required by provider | SMTP authentication credentials. |
| `SMTP_FROM_EMAIL` | Yes | Authorized sender address. |
| `SMTP_USE_TLS` | No | `true` (default) uses STARTTLS; `false` disables STARTTLS. |

Never put SMTP credentials in source control or frontend configuration. If the
organization lacks a verified contact, the SMTP settings are incomplete, or
the provider rejects delivery, schedule creation remains persisted and returns
`organization_notified: false` with a visible failure state. Each requested
notification is kept in the PostgreSQL outbox with its attempt count and last
failure; an Authority Officer can retry it after correcting the contact or
provider configuration. A pending or failed notification does not undo a valid
schedule.

These endpoints and notifications are **not live until this backend has been
deployed, its startup migrations have run, Authority Officer sessions are
configured, organization contacts have been verified, and SMTP is configured
with a delivery provider**.
