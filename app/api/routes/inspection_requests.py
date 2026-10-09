"""Public request submission and protected Authority Officer review endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.security import require_authority_officer
from app.schemas.inspection_request import (
    InspectionRequest,
    InspectionRequestCreate,
    InspectionRequestReview,
)
from app.services import inspection_request_service

public_router = APIRouter(tags=["Inspection Requests"])
authority_router = APIRouter(tags=["Inspection Requests"])


@public_router.post(
    "/inspection-requests",
    response_model=InspectionRequest,
    status_code=status.HTTP_201_CREATED,
)
def submit_request(payload: InspectionRequestCreate, request: Request):
    """Submit an unverified department request; this does not authorize an inspection."""
    client_host = request.client.host if request.client else "unknown"
    try:
        return inspection_request_service.submit_inspection_request(payload, client_host)
    except inspection_request_service.RateLimitExceeded as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@authority_router.get(
    "/inspection-requests",
    response_model=list[InspectionRequest],
    dependencies=[Depends(require_authority_officer)],
)
def list_requests():
    return inspection_request_service.get_inspection_requests()


@authority_router.patch(
    "/inspection-requests/{request_id}",
    response_model=InspectionRequest,
)
def review_request(
    request_id: str,
    payload: InspectionRequestReview,
    claims: dict = Depends(require_authority_officer),
):
    try:
        return inspection_request_service.review_inspection_request(
            request_id,
            payload.status,
            claims["sub"],
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except inspection_request_service.InvalidRequestTransition as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
