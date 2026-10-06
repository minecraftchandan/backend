"""Export the local Satark Drishti SQLite data as PostgreSQL INSERT statements."""

import argparse
import sqlite3
from pathlib import Path


TABLES = {
    "users": ("id",),
    "organizations": ("id",),
    "schedules": ("id",),
    "deleted_inspections": ("id",),
    "inspections": ("id",),
    "portal_data": ("data_key",),
    "portal_settings": ("setting_id",),
    "accounts": ("username",),
    "evidence_media": ("media_id",),
    "reverse_geocode_cache": ("cache_key",),
}


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return f"decode('{value.hex()}', 'hex')"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"Unsupported SQLite value type: {type(value).__name__}")


def export_database(source: Path, output: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"SQLite database not found: {source}")

    connection = sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    statements = [
        "-- Satark Drishti SQLite data export for PostgreSQL.",
        "-- Run after the deployment API has initialized the matching PostgreSQL schema.",
        "-- Contains account password hashes and inspection evidence image bytes; keep private.",
        "BEGIN;",
    ]
    try:
        existing_tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        for table, conflict_columns in TABLES.items():
            if table not in existing_tables:
                continue
            rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
            if not rows:
                continue
            columns = rows[0].keys()
            column_list = ", ".join(f'"{column}"' for column in columns)
            placeholders = ", ".join(["%s"] * len(columns))
            conflict_target = ", ".join(f'"{column}"' for column in conflict_columns)
            updates = ", ".join(
                f'"{column}" = EXCLUDED."{column}"'
                for column in columns
                if column not in conflict_columns
            )
            conflict_action = (
                f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
            )
            for row in rows:
                values = ", ".join(sql_literal(row[column]) for column in columns)
                statements.append(
                    f'INSERT INTO "{table}" ({column_list}) VALUES ({values}) '
                    f"ON CONFLICT ({conflict_target}) {conflict_action};"
                )
        statements.extend(
            [
                "DELETE FROM inspections WHERE id IN (SELECT id FROM deleted_inspections);",
                "COMMIT;",
            ]
        )
    finally:
        connection.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(statements) + "\n", encoding="utf-8")


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=project_root / "backend" / "data" / "satark.sqlite3",
        help="SQLite database file to export.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "backend&db" / "local-import.sql",
        help="PostgreSQL SQL output file.",
    )
    args = parser.parse_args()
    export_database(args.source, args.output)
    print(f"PostgreSQL import SQL written to: {args.output.resolve()}")


if __name__ == "__main__":
    main()
