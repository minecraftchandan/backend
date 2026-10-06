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
