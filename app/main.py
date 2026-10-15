"""
Satark Drishti — Backend (Member 3)

FastAPI application entry point. Run with:

    uvicorn app.main:app --reload

Swagger docs are available at /docs once the server is running.
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.api.routes.auth import router as auth_router
from app.api.routes.inspection_requests import public_router as public_inspection_requests_router
from app.api.routes.users import public_router as public_users_router
from app.database import initialize_database

load_dotenv()  # loads variables from a local .env file, if present
app_environment = os.getenv("APP_ENV", "development").strip().lower()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield

app = FastAPI(
    title="Satark Drishti — Backend",
    description=(
        "Satark Drishti API backed by PostgreSQL for users, inspection schedules, "
        "inspection records, and camera evidence."
    ),
    version="0.1.0",
    docs_url=None if app_environment == "production" else "/docs",
    redoc_url=None if app_environment == "production" else "/redoc",
    openapi_url=None if app_environment == "production" else "/openapi.json",
    lifespan=lifespan,
)

# CORS: allow the Inspector Portal (Member 2) to call this API from the
# browser during local development. Configurable via .env / ALLOWED_ORIGINS.
_default_origins = ",".join(
    f"http://{host}:{port}"
    for port in (4175, 4176, 4177, 4178, 5173, 5174)
    for host in ("localhost", "127.0.0.1")
) + ",https://localhost"
allowed_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",")
    if origin.strip()
]
if "*" in allowed_origins:
    raise ValueError("ALLOWED_ORIGINS must not contain a wildcard")

trusted_hosts = [
    host.strip()
    for host in os.getenv("TRUSTED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
if not trusted_hosts or "*" in trusted_hosts:
    raise ValueError("TRUSTED_HOSTS must contain explicit hostnames")

app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Cross-Origin-Resource-Policy"] = (
        "cross-origin" if request.url.path.startswith("/api/media/") else "same-origin"
    )
    return response


@app.get("/api/health", tags=["Health"])
def health_check():
    """Simple liveness check for the backend."""
    return {"status": "ok"}


app.include_router(public_inspection_requests_router, prefix="/api")
app.include_router(public_users_router, prefix="/api")
app.include_router(api_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
