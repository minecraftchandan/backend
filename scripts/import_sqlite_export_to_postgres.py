"""Import the generated local SQLite data dump into the PostgreSQL backend."""

import getpass
import os
import re
import sys
from pathlib import Path

import psycopg


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DUMP = PROJECT_ROOT / "backend&db" / "local-import.sql"
ALLOWED_TABLES = {
    "users",
    "organizations",
    "schedules",
    "deleted_inspections",
    "inspections",
    "portal_data",
    "portal_settings",
    "accounts",
    "evidence_media",
    "reverse_geocode_cache",
}


def split_sql_statements(script: str) -> list[str]:
    """Split generated SQL at semicolons outside strings, identifiers, and comments."""
    statements: list[str] = []
    start = 0
    index = 0
    in_string = False
    in_identifier = False
    in_line_comment = False
    in_block_comment = False

    while index < len(script):
        char = script[index]
        next_char = script[index + 1] if index + 1 < len(script) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
        elif in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 1
        elif in_string:
            if char == "'" and next_char == "'":
                index += 1
            elif char == "'":
                in_string = False
        elif in_identifier:
            if char == '"' and next_char == '"':
                index += 1
            elif char == '"':
                in_identifier = False
        elif char == "-" and next_char == "-":
            in_line_comment = True
            index += 1
        elif char == "/" and next_char == "*":
            in_block_comment = True
            index += 1
        elif char == "'":
            in_string = True
        elif char == '"':
            in_identifier = True
        elif char == ";":
            statement = re.sub(
                r"^(?:\s*--[^\n]*(?:\n|$))+",
                "",
                script[start:index],
            ).strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1

    if in_string or in_identifier or in_block_comment:
        raise ValueError("The PostgreSQL import file contains an unterminated SQL quote or comment.")
    trailing_statement = re.sub(
        r"^(?:\s*--[^\n]*(?:\n|$))+",
        "",
        script[start:],
    ).strip()
    if trailing_statement and not trailing_statement.startswith("--"):
        raise ValueError("The PostgreSQL import file has an incomplete trailing statement.")
    return statements


def validate_dump(statements: list[str]) -> None:
    if len(statements) < 2 or statements[0].upper() != "BEGIN":
        raise ValueError("Import file must begin with BEGIN;.")
    if statements[-1].upper() != "COMMIT":
        raise ValueError("Import file must end with COMMIT;.")
    for statement in statements[1:-1]:
        insert_match = re.match(r'^INSERT\s+INTO\s+"([^"]+)"\s', statement, re.IGNORECASE)
        if insert_match and insert_match.group(1) in ALLOWED_TABLES:
            continue
        if statement == "DELETE FROM inspections WHERE id IN (SELECT id FROM deleted_inspections)":
            continue
        raise ValueError("Import file contains an unsupported statement; refusing to execute it.")


def import_dump(database_url: str, dump_path: Path = DEFAULT_DUMP) -> int:
    if not dump_path.is_file():
        raise FileNotFoundError(f"PostgreSQL import file not found: {dump_path}")
    script = dump_path.read_text(encoding="utf-8")
    statements = split_sql_statements(script)
    validate_dump(statements)

    with psycopg.connect(database_url, connect_timeout=15) as connection:
        with connection.transaction():
            for statement in statements[1:-1]:
                connection.execute(statement)
            connection.execute(
                """UPDATE users
                SET department_unit = COALESCE(department_unit, 'Inspection Department'),
                    jurisdiction = COALESCE(jurisdiction, region),
                    active = COALESCE(active, TRUE)"""
            )
            connection.execute(
                """UPDATE schedules
                SET inspector_id = (
                    SELECT id FROM users
                    WHERE users.name = schedules.inspector ORDER BY id LIMIT 1
                )
                WHERE inspector_id IS NULL AND EXISTS (
                    SELECT 1 FROM users WHERE users.name = schedules.inspector
                )"""
            )
    return len(statements) - 2


def main() -> None:
    dump_path = Path(os.getenv("SQLITE_POSTGRES_DUMP", str(DEFAULT_DUMP))).expanduser()
    database_url = os.getenv("NEON_DATABASE_URL", "").strip()
    if not database_url:
        database_url = getpass.getpass("Neon PostgreSQL connection URL (input hidden): ").strip()
    if not database_url:
        raise ValueError("A Neon PostgreSQL connection URL is required.")

    os.environ["DATABASE_URL"] = database_url
    deployment_root = PROJECT_ROOT / "backend&db"
    sys.path.insert(0, str(deployment_root))
    from app.database import initialize_database

    print("Creating backend tables and initializing the PostgreSQL schema...")
    initialize_database()
    print("Importing SQLite data...")
    statement_count = import_dump(database_url, dump_path)
    print(f"Imported {statement_count} SQL statements from {dump_path}.")


if __name__ == "__main__":
    main()
