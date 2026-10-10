"""Persistence for public department requests and Authority Officer reviews."""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from app.database import get_connection
from app.schemas.inspection_request import InspectionRequest, InspectionRequestCreate

RATE_LIMIT_REQUESTS = 5


def _row_to_request(row: dict) -> InspectionRequest:
    data = dict(row)
    raw = data.pop("new_organization_json", None)
    # new_organization may be a JSON object (from previous session) or plain text
    if raw:
        try:
            data["new_organization"] = json.loads(raw)
        except (ValueError, TypeError):
            data["new_organization"] = raw
    else:
        data["new_organization"] = data.get("new_organization") or None
    # map stored columns to response aliases
    data.setdefault("proposed_scope", data.get("scope", ""))
    data.setdefault("priority", data.get("urgency", "Routine"))
    data.setdefault("contact", data.get("requester_email", ""))
    return InspectionRequest.model_validate(data)


def _request_view(connection, request_id: str) -> InspectionRequest | None:
    row = connection.execute(
        """SELECT r.id, r.department, r.contact, r.requester_name, r.requester_email,
            r.requester_verified, r.organization_id,
            COALESCE(o.name, r.organization_display) AS organization,
            r.purpose, r.scope, r.urgency, r.proposed_scope, r.priority,
            r.status, r.created_at, r.reviewed_by, r.reviewed_at,
            r.new_organization AS new_organization_json
        FROM inspection_requests r
        LEFT JOIN organizations o ON o.id = r.organization_id
        WHERE r.id = ?""",
        (request_id,),
    ).fetchone()
    return _row_to_request(dict(row)) if row else None


def submit_inspection_request(
    payload: InspectionRequestCreate,
    client_host: str,
) -> InspectionRequest:
    now = datetime.now(timezone.utc)
    window_start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    bucket_key = hashlib.sha256(client_host.encode("utf-8")).hexdigest()

    with get_connection() as connection:
        rate = connection.execute(
            """INSERT INTO inspection_request_rate_limits
                (bucket_key, window_start, request_count)
            VALUES (?, ?, 1)
            ON CONFLICT (bucket_key, window_start)
            DO UPDATE SET request_count = inspection_request_rate_limits.request_count + 1
            RETURNING request_count""",
            (bucket_key, window_start),
        ).fetchone()
        connection.execute(
            "DELETE FROM inspection_request_rate_limits WHERE window_start < ?",
            (now - timedelta(days=1),),
        )
    if rate["request_count"] > RATE_LIMIT_REQUESTS:
        raise RateLimitExceeded("Too many inspection requests. Try again after the current 15-minute window.")

    # resolve effective scope/urgency from either alias set
    effective_scope = payload.proposed_scope or payload.scope or ""
    effective_urgency = payload.priority or payload.urgency or "Routine"
    effective_contact = payload.contact or payload.requester_email or ""
    # new_organization: plain text string from frontend
    new_org_value = payload.new_organization if isinstance(payload.new_organization, str) else (
        json.dumps(payload.new_organization.model_dump()) if payload.new_organization else None
    )

    with get_connection() as connection:
        if payload.organization_id:
            org = connection.execute(
                "SELECT id FROM organizations WHERE id = ?", (payload.organization_id,)
            ).fetchone()
            if org is None:
                raise LookupError("The selected organization is not registered.")
        request_id = f"IR-{uuid.uuid4().hex[:16].upper()}"
        connection.execute(
            """INSERT INTO inspection_requests
            (id, department, contact, requester_name, requester_email, requester_verified,
            organization_id, organization_display, purpose, scope, urgency,
            proposed_scope, priority, status, created_at, new_organization)
            VALUES (?, ?, ?, ?, ?, FALSE, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)""",
            (
                request_id,
                payload.department,
                effective_contact,
                payload.requester_name or "",
                payload.requester_email or "",
                payload.organization_id,
                payload.organization,
                payload.purpose or "",
                effective_scope,
                effective_urgency,
                effective_scope,
                effective_urgency,
                now.isoformat(),
                new_org_value,
            ),
        )
        result = _request_view(connection, request_id)
    if result is None:
        raise RuntimeError("The inspection request could not be loaded after insertion.")
    return result


def get_inspection_requests() -> list[InspectionRequest]:
    with get_connection() as connection:
        rows = connection.execute(
            """SELECT r.id, r.department, r.contact, r.requester_name, r.requester_email,
                r.requester_verified, r.organization_id,
                COALESCE(o.name, r.organization_display) AS organization,
                r.purpose, r.scope, r.urgency, r.proposed_scope, r.priority,
                r.status, r.created_at, r.reviewed_by, r.reviewed_at,
                r.new_organization AS new_organization_json
            FROM inspection_requests r
            LEFT JOIN organizations o ON o.id = r.organization_id
            ORDER BY r.created_at DESC, r.id"""
        ).fetchall()
    return [_row_to_request(dict(row)) for row in rows]


def review_inspection_request(
    request_id: str,
    new_status: str,
    reviewer: str,
) -> InspectionRequest:
    stored_status = "Rejected" if new_status == "Flagged" else new_status
    reviewed_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        result = connection.execute(
            """UPDATE inspection_requests
            SET status = ?, reviewed_by = ?, reviewed_at = ?
            WHERE id = ? AND status = 'Pending'""",
            (stored_status, reviewer, reviewed_at, request_id),
        )
        if result.rowcount == 0:
            existing = _request_view(connection, request_id)
            if existing is None:
                raise LookupError("Inspection request not found.")
            raise InvalidRequestTransition(
                f"Inspection request is already {existing.status.lower()} and cannot be reviewed again."
            )
        updated = _request_view(connection, request_id)
    if updated is None:
        raise RuntimeError("The reviewed inspection request could not be loaded.")
    return updated


class RateLimitExceeded(Exception):
    """Raised when a source exceeds the public request submission allowance."""


class InvalidRequestTransition(Exception):
    """Raised when a closed request is reviewed a second time."""
