"""SQLite-backed organization registry and inspection summary queries."""

import re
import uuid

from app.database import get_connection
from app.schemas.organization import Organization, OrganizationCreate


def get_all_organizations() -> list[Organization]:
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT o.id, o.name, o.reg, o.location, o.address,
                COALESCE(MAX(i.date), '') AS last,
                COALESCE(MIN(CASE WHEN s.status = 'Scheduled' THEN s.date END), '') AS next,
                o.verification, o.risk, COUNT(DISTINCT i.id) AS count,
                o.latitude, o.longitude, o.radius_m
            FROM organizations o
            LEFT JOIN inspections i ON i.organization = o.name
            LEFT JOIN schedules s ON s.organization = o.name
            GROUP BY o.id
            ORDER BY o.created_at, o.name"""
        ).fetchall()
    return [Organization.model_validate(dict(row)) for row in rows]


def get_organization_by_id(organization_id: str) -> Organization | None:
    return next((item for item in get_all_organizations() if item.id == organization_id), None)


def create_organization(data: OrganizationCreate) -> Organization:
    if (data.latitude is None) != (data.longitude is None):
        raise ValueError("Provide both latitude and longitude, or leave both empty.")
    if data.radius_m is not None and data.latitude is None:
        raise ValueError("A verification radius requires site coordinates.")

    slug = re.sub(r"[^a-z0-9]+", "-", data.name.lower()).strip("-")[:50] or "organization"
    organization_id = f"{slug}-{uuid.uuid4().hex[:8]}"
    with get_connection() as connection:
        for attempt in range(3):
            registration_id = f"SD-ORG-{uuid.uuid4().hex[:12].upper()}"
            result = connection.execute(
                """INSERT INTO organizations
                (id, name, reg, location, address, verification, risk, latitude, longitude, radius_m)
                VALUES (?, ?, ?, ?, ?, 'Pending', 'Review', ?, ?, ?)
                ON CONFLICT (reg) DO NOTHING""",
                (
                    organization_id,
                    data.name.strip(),
                    registration_id,
                    data.location.strip(),
                    data.address.strip(),
                    data.latitude,
                    data.longitude,
                    data.radius_m,
                ),
            )
            if result.rowcount:
                break
            if attempt == 2:
                raise ValueError("Could not generate a unique organization registration ID.")
    return get_organization_by_id(organization_id)


def update_organization_verification(
    organization_id: str,
    verification: str,
) -> Organization | None:
    risk = "Low attention" if verification == "Verified" else "High attention"
    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE organizations SET verification = ?, risk = ? WHERE id = ?",
            (verification, risk, organization_id),
        )
        if cursor.rowcount == 0:
            return None
    return get_organization_by_id(organization_id)


def delete_organization(organization_id: str) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM organizations WHERE id = ?",
            (organization_id,),
        )
    return cursor.rowcount > 0