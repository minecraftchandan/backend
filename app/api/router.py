"""
Combines all feature routers into a single API router.
Mounted under the "/api" prefix in app/main.py.
"""

from fastapi import APIRouter, Depends

from app.api.routes import inspection_requests, inspections, organizations, portal, schedules, users
from app.api.security import require_api_access

api_router = APIRouter(dependencies=[Depends(require_api_access)])

api_router.include_router(users.router)
api_router.include_router(schedules.router)
api_router.include_router(inspection_requests.authority_router)
api_router.include_router(inspections.router)
api_router.include_router(organizations.router)
api_router.include_router(portal.router)
