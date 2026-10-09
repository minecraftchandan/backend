"""Organization registry endpoints."""

import psycopg

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.security import require_authority_officer
from app.schemas.organization import (
    Organization,
    OrganizationCreate,
    OrganizationVerifiedContactUpdate,
    OrganizationVerificationUpdate,
)
from app.services import organization_service

router = APIRouter(tags=["Organizations"])


@router.get("/organizations", response_model=list[Organization])
def list_organizations():
    return organization_service.get_all_organizations()


@router.get("/organizations/{organization_id}", response_model=Organization)
def get_organization(organization_id: str):
    organization = organization_service.get_organization_by_id(organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


@router.post("/organizations", response_model=Organization, status_code=status.HTTP_201_CREATED)
def create_organization(payload: OrganizationCreate):
    try:
        return organization_service.create_organization(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except psycopg.IntegrityError as error:
        raise HTTPException(status_code=409, detail="An organization with this name or registration ID already exists.") from error


@router.put("/organizations/{organization_id}/status", response_model=Organization)
def update_organization_verification(
    organization_id: str,
    payload: OrganizationVerificationUpdate,
):
    organization = organization_service.update_organization_verification(
        organization_id,
        payload.verification,
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


@router.patch(
    "/organizations/{organization_id}/verified-contact",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_authority_officer)],
)
def set_verified_organization_contact(
    organization_id: str,
    payload: OrganizationVerifiedContactUpdate,
):
    if not organization_service.set_verified_organization_contact(
        organization_id,
        payload.contact_email,
        payload.contact_person,
    ):
        raise HTTPException(status_code=404, detail="Organization not found")


@router.delete("/organizations/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(organization_id: str):
    try:
        if not organization_service.delete_organization(organization_id):
            raise HTTPException(status_code=404, detail="Organization not found")
    except psycopg.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="Organization cannot be deleted while inspection requests reference it.",
        ) from error