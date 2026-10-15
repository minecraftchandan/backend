"""Service for the authority portal's persisted demo payload."""

import json

from app.database import get_connection


def get_portal_data() -> dict:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT payload FROM portal_data WHERE data_key = ?",
            ("demo",),
        ).fetchone()
        settings_row = connection.execute(
            "SELECT payload FROM portal_settings WHERE setting_id = 1"
        ).fetchone()

    if row is None:
        return {}
    payload = json.loads(row["payload"])
    if settings_row:
        payload["settings"] = json.loads(settings_row["payload"])
    return payload


def update_portal_settings(settings: dict) -> dict:
    serialized = json.dumps(settings)
    with get_connection() as connection:
        connection.execute(
            "UPDATE portal_settings SET payload = ? WHERE setting_id = 1",
            (serialized,),
        )
    return settings


def get_evidence_media(
    media_id: str,
    inspector_id: int | None = None,
) -> tuple[str, bytes] | None:
    with get_connection() as connection:
        if inspector_id is None:
            row = connection.execute(
                "SELECT media_type, content FROM evidence_media WHERE media_id = ?",
                (media_id,),
            ).fetchone()
        else:
            row = connection.execute(
                """SELECT m.media_type, m.content FROM evidence_media m
                WHERE m.media_id = ? AND EXISTS (
                    SELECT 1 FROM inspections i
                    JOIN schedules s ON s.id = i.schedule_id
                    WHERE i.photo_media_id = m.media_id
                    AND COALESCE(
                        s.inspector_id,
                        (SELECT id FROM users WHERE name = s.inspector ORDER BY id LIMIT 1)
                    ) = ?
                )""",
                (media_id, inspector_id),
            ).fetchone()
    if row is None:
        return None
    return row["media_type"], row["content"]
